from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Any, Dict, Sequence, cast, Iterable

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

MAX_FOLLOW_UP_QUESTIONS = 5
FOLLOW_UP_PRIORITY: Sequence[str] = (
    "activity_details",
    "counterparty_relationship",
    "activity_background",
    "target_product",
    "affiliation",
)
FOLLOW_UP_PRIORITY_INDEX: Dict[str, int] = {
    field: idx for idx, field in enumerate(FOLLOW_UP_PRIORITY)
}

FOLLOW_UP_PROMPT_TEMPLATE = """
あなたは契約申請フォームの補足回答を整理するアシスタントです。推測はせず、元のテキストとユーザ回答に記載された事実のみを使ってください。

入力:
- source_text: 元の会話・資料テキスト。
- current_form: 現在のフォーム値（空文字は未入力を意味します）。
- qa: 追加質問とその回答のリスト。回答が空文字のものは含まれていません。

出力は次のJSONのみ:
{{
  "updated_form": {{
    "affiliation": 文字列または null,
    "target_product": 文字列または null,
    "activity_background": 文字列または null,
    "counterparty_relationship": 文字列または null,
    "activity_details": 文字列または null
  }},
  "explanation": {{
    "affiliation": {{"action": "updated" | "unchanged", "reason": 文字列}},
    "target_product": {{"action": "updated" | "unchanged", "reason": 文字列}},
    "activity_background": {{"action": "updated" | "unchanged", "reason": 文字列}},
    "counterparty_relationship": {{"action": "updated" | "unchanged", "reason": 文字列}},
    "activity_details": {{"action": "updated" | "unchanged", "reason": 文字列}}
  }},
  "follow_up_questions": 日本語の短い質問（0〜5件）の配列
}}

更新方針:
- 回答が具体的に情報を補完する場合のみ該当欄を更新してください。確信が持てない場合は既存値を維持します。
- 回答で明らかに誤りや矛盾がある場合は更新せず、理由を explanation に記載してください。
- 未充足の情報がある場合のみ follow_up_questions を最大5件まで生成します。不要なら空配列にしてください。

source_text:
{source_text}

current_form:
{current_form}

qa:
{qa}
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
    follow_ups = _prioritize_follow_up_questions(payload.get("follow_up_questions"))
    if follow_ups:
        result["follow_up_questions"] = follow_ups
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


def update_form_with_followups(
    source_text: str,
    current_form: Dict[str, Any],
    qa: Sequence[Dict[str, str]],
    current_round: int = 1,
    max_rounds: int = 2,
) -> Dict[str, Any]:
    """Use Gemini (or fallback heuristics) to merge follow-up answers into form values."""
    qa = [item for item in qa if item.get("answer")]
    if not qa:
        return {
            "form": current_form,
            "follow_up_questions": [],
            "next_round": current_round,
            "max_rounds_reached": current_round >= max_rounds,
            "explanation": {},
        }

    try:
        payload = _call_gemini_follow_up(source_text, current_form, qa)
    except GeminiConfigError as exc:
        logger.info("Gemini follow-up unavailable: %s", exc)
        fallback_form = _apply_follow_up_fallback(current_form, qa)
        next_round, follow_ups, maxed = _calculate_follow_up_rounds(
            current_round, max_rounds, []
        )
        return {
            "form": fallback_form,
            "follow_up_questions": follow_ups,
            "error": str(exc),
            "next_round": next_round,
            "max_rounds_reached": maxed,
            "explanation": {},
        }
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Gemini follow-up update failed: %s", exc)
        fallback_form = _apply_follow_up_fallback(current_form, qa)
        next_round, follow_ups, maxed = _calculate_follow_up_rounds(
            current_round, max_rounds, []
        )
        return {
            "form": fallback_form,
            "follow_up_questions": follow_ups,
            "error": "Geminiの更新に失敗しました。",
            "next_round": next_round,
            "max_rounds_reached": maxed,
            "explanation": {},
        }

    updated_form = _merge_form_updates(current_form, payload.get("updated_form", {}))
    raw_follow_ups = payload.get("follow_up_questions") if isinstance(payload, dict) else []
    prioritized = _prioritize_follow_up_questions(raw_follow_ups)
    next_round, follow_up_questions, maxed = _calculate_follow_up_rounds(
        current_round, max_rounds, prioritized
    )
    explanation = payload.get("explanation") if isinstance(payload, dict) else {}
    return {
        "form": updated_form,
        "follow_up_questions": follow_up_questions,
        "explanation": explanation if isinstance(explanation, dict) else {},
        "next_round": next_round,
        "max_rounds_reached": maxed,
    }


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


def _call_gemini_follow_up(
    source_text: str,
    current_form: Dict[str, Any],
    qa: Sequence[Dict[str, str]],
) -> Dict[str, Any]:
    client = _get_client()
    prompt = FOLLOW_UP_PROMPT_TEMPLATE.format(
        source_text=source_text.strip(),
        current_form=json.dumps(current_form, ensure_ascii=False, indent=2),
        qa=json.dumps(list(qa), ensure_ascii=False, indent=2),
    )
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


_KEYWORDS_MAP: Dict[str, Sequence[str]] = {
    "affiliation": ("所属", "部署"),
    "target_product": ("対象", "商材", "製品", "プロダクト", "サービス"),
    "activity_background": ("背景", "目的"),
    "counterparty_relationship": ("相手", "関係", "関連契約", "既締結"),
    "activity_details": ("活動内容", "予定", "実施", "進め方"),
}


def _apply_follow_up_fallback(
    current_form: Dict[str, Any],
    qa: Sequence[Dict[str, str]],
) -> Dict[str, Any]:
    merged = dict(current_form)
    remaining_fields = [
        field
        for field in FORM_FIELD_NAMES
        if field != "source_text" and not (merged.get(field) or "").strip()
    ]
    for item in qa:
        question = str(item.get("question", "") or "")
        answer = str(item.get("answer", "") or "").strip()
        if not answer:
            continue
        target_field = _infer_field_from_question(question)
        if not target_field and remaining_fields:
            target_field = remaining_fields[0]
        if target_field and target_field in FORM_FIELD_NAMES:
            merged[target_field] = answer
            if target_field in remaining_fields:
                remaining_fields.remove(target_field)
    return merged


def _infer_field_from_question(question: str) -> str | None:
    for field, keywords in _KEYWORDS_MAP.items():
        if any(keyword in question for keyword in keywords):
            return field
    return None


def _merge_form_updates(
    current_form: Dict[str, Any],
    updated_form: Dict[str, Any],
) -> Dict[str, Any]:
    merged = dict(current_form)
    if not isinstance(updated_form, dict):
        return merged
    for field in FORM_FIELD_NAMES:
        if field == "source_text":
            continue
        if field in updated_form:
            value = updated_form[field]
            # Allow explicit clearing with null/empty string
            if value is None:
                merged[field] = ""
            else:
                merged[field] = str(value).strip()
    return merged


def _prioritize_follow_up_questions(raw_questions: Any) -> list[Any]:
    if not isinstance(raw_questions, Sequence):
        return []
    prioritized: list[tuple[int, int, Any]] = []
    for idx, item in enumerate(raw_questions):
        question_text = ""
        field: str | None = None
        if isinstance(item, dict):
            question_text = str(item.get("question", "") or "")
            target_field = item.get("target")
            if isinstance(target_field, str) and target_field in FORM_FIELD_NAMES:
                field = target_field
        else:
            question_text = str(item)
        if not field:
            field = _infer_field_from_question(question_text)
        priority = FOLLOW_UP_PRIORITY_INDEX.get(field or "", len(FOLLOW_UP_PRIORITY))
        prioritized.append((priority, idx, item))
    prioritized.sort(key=lambda x: (x[0], x[1]))
    return [item for _, _, item in prioritized][:MAX_FOLLOW_UP_QUESTIONS]


def _calculate_follow_up_rounds(
    current_round: int,
    max_rounds: int,
    questions: Sequence[Any],
) -> tuple[int, list[Any], bool]:
    if current_round >= max_rounds:
        return current_round, [], True
    next_round = min(current_round + 1, max_rounds)
    limited_questions = list(questions)[:MAX_FOLLOW_UP_QUESTIONS]
    maxed = next_round >= max_rounds or not limited_questions
    return next_round, limited_questions, maxed


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
