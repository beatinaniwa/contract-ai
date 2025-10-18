from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Any, Dict, Sequence, cast

from google import genai
from pydantic import ValidationError

from models.schemas import ContractForm
from config_loader import ConfigNotFoundError, load_secret
from .validator import validate_form

logger = logging.getLogger(__name__)


class GeminiConfigError(RuntimeError):
    """Raised when Gemini configuration is missing or invalid."""


GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
FORM_FIELD_NAMES = [name for name in ContractForm.model_fields if name != "source_text"]
PROMPT_TEMPLATE = """
あなたは日本語の打ち合わせメモから契約申請フォームの情報を抽出するアシスタントです。
出力はJSONのみで、余分な文章やマークダウンを含めないでください。
全てのキーを含む "form" オブジェクトを生成し、値が不明な場合は null を設定します。

必須のJSON構造:
{{
  "form": {{
    "affiliation": 文字列または null,
    "target_product": 文字列または null,
    "activity_background": 文字列または null,
    "counterparty_relationship": 文字列または null,
    "activity_details": 文字列または null
  }},
  "follow_up_questions": 日本語の短い質問（0〜5件）の配列
}}

フィールドごとの指針:
- affiliation: 依頼者の所属・部署をそのまま抜き出してください。
- target_product: 対象となる商材/プロダクト/サービス名を記載してください。
- activity_background: 活動の背景や目的を要約してください。
- counterparty_relationship: 相手方との関係性や既存の契約状況をまとめてください。
- activity_details: 実際に行う活動内容を具体的に記載してください。
推測は禁止し、根拠が無ければ null を設定してください。

入力テキスト:
{conversation}
"""

FIELD_PATTERNS: Dict[str, Sequence[re.Pattern[str]]] = {
    "affiliation": (
        re.compile(r"(?:所属|所属部署|部署名?)[:：][\t 　]*([^\n]+)"),
        re.compile(r"部署(?:は|：)[\t 　]*([^\n]+)"),
    ),
    "target_product": (
        re.compile(r"(?:対象商材|商材|対象プロダクト|プロダクト|製品)[:：][\t 　]*([^\n]+)"),
        re.compile(r"対象は[\t 　]*([^\n]+)"),
    ),
    "activity_background": (
        re.compile(r"(?:活動背景|背景|目的|狙い)[:：][\t 　]*([^\n]+)"),
        re.compile(r"(?:活動の背景|背景と目的)[\t 　]*[:：]?[\t 　]*([^\n]+)"),
    ),
    "counterparty_relationship": (
        re.compile(r"(?:相手方|相手|取引先|カウンターパーティ)[^\n]*[:：][\t 　]*([^\n]+)"),
        re.compile(r"(?:既締結|既存)の?(?:契約|合意)[^\n]*[:：][\t 　]*([^\n]+)"),
    ),
    "activity_details": (
        re.compile(r"(?:活動内容|予定している活動|実施内容|対応内容)[:：][\t 　]*([^\n]+)"),
        re.compile(r"(?:実施予定|進め方)[:：][\t 　]*([^\n]+)"),
    ),
}


def extract_contract_form(text: str) -> Dict[str, Any]:
    if not text or not text.strip():
        return {"form": {}, "missing_fields": [], "error": "入力テキストが空です。"}

    try:
        return _extract_with_gemini(text)
    except GeminiConfigError as exc:
        logger.info("Gemini configuration issue: %s", exc)
        fallback = _extract_with_regex(text)
        fallback["error"] = str(exc)
        return fallback
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Gemini extraction failed: %s", exc)
        fallback = _extract_with_regex(text)
        fallback["error"] = "Gemini抽出でエラーが発生したため、正規表現ベースの抽出結果を表示しています。"
        return fallback


def gemini_healthcheck() -> tuple[bool, str]:
    """Perform a minimal request to verify Gemini connectivity and model availability."""
    try:
        client = _get_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents="ping",
        )
        feedback = getattr(response, "prompt_feedback", None)
        if feedback and getattr(feedback, "block_reason", None):
            return False, f"Blocked by safety: {feedback.block_reason}"
        content = getattr(response, "text", None)
        if not content:
            return False, "Empty response"
        return True, "OK"
    except GeminiConfigError as exc:
        return False, f"Config error: {exc}"
    except Exception as exc:  # pragma: no cover - external API variations
        return False, f"API error: {exc.__class__.__name__}: {exc}"


def _extract_with_gemini(text: str) -> Dict[str, Any]:
    payload = _call_gemini(text)
    raw_form = payload.get("form", {})
    if not isinstance(raw_form, dict):
        raise ValueError("Gemini response did not include a valid 'form' object")

    form = _coerce_form(raw_form)
    out_form = form.model_dump(exclude_none=True)

    _, missing = validate_form(form)
    result: Dict[str, Any] = {"form": out_form, "missing_fields": missing}
    follow_ups = payload.get("follow_up_questions")
    if isinstance(follow_ups, list) and follow_ups:
        result["follow_up_questions"] = follow_ups[:5]
    return result


def _extract_with_regex(text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    source = text or ""

    for field, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(source)
            if match:
                extracted = match.group(1).strip()
                if extracted:
                    data[field] = extracted
                    break

    form = _coerce_form(data)
    out_form = form.model_dump(exclude_none=True)
    _, missing = validate_form(form)
    return {"form": out_form, "missing_fields": missing}


def _coerce_form(raw_form: Dict[str, Any]) -> ContractForm:
    cleaned = _normalize_form_payload(raw_form)
    try:
        return ContractForm(**cleaned)
    except ValidationError as exc:
        for error in exc.errors():
            raw_loc = error.get("loc")
            loc: Sequence[object] = (
                cast(Sequence[object], raw_loc) if isinstance(raw_loc, (list, tuple)) else []
            )
            field = loc[0] if loc else None
            if isinstance(field, str):
                cleaned.pop(field, None)
        return ContractForm(**cleaned)


def _normalize_form_payload(raw_form: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key in FORM_FIELD_NAMES:
        if key not in raw_form:
            continue
        value = raw_form[key]
        if value is None:
            continue
        if isinstance(value, list):
            joined = "\n".join(str(item).strip() for item in value if str(item).strip())
            value = joined or None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            value = stripped
        normalized[key] = value
    return normalized


def _call_gemini(text: str) -> Dict[str, Any]:
    client = _get_client()
    prompt = PROMPT_TEMPLATE.format(conversation=text.strip())
    response = client.models.generate_content(
        model=GEMINI_MODEL_NAME,
        contents=prompt,
    )
    feedback = getattr(response, "prompt_feedback", None)
    if feedback and getattr(feedback, "block_reason", None):
        raise ValueError(f"Gemini blocked the prompt: {feedback.block_reason}")

    content = getattr(response, "text", None)
    if not content:
        raise ValueError("Gemini response was empty")

    return _load_json(content)


def _load_json(raw_text: str) -> Dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("Gemini応答のJSON解析に失敗しました") from exc


def _get_api_key() -> str:
    try:
        api_key = load_secret("gemini_api_key")
    except ConfigNotFoundError as exc:
        raise GeminiConfigError(str(exc)) from exc

    if not api_key:
        raise GeminiConfigError(".streamlit/secrets.toml に gemini_api_key を設定してください。")

    return api_key


@lru_cache(maxsize=1)
def _get_client():
    api_key = _get_api_key()
    return genai.Client(api_key=api_key)
