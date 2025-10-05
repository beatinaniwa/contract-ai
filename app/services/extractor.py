import json
import logging
import os
import re
from functools import lru_cache
from typing import Any, Dict

from google import genai
from dateutil import parser
from pydantic import ValidationError

from models.schemas import ContractForm
from config_loader import ConfigNotFoundError, load_secret
from .normalizer import normalize_amount_jpy
from .validator import validate_form

logger = logging.getLogger(__name__)


class GeminiConfigError(RuntimeError):
    """Raised when Gemini configuration is missing or invalid."""


GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
FORM_FIELD_NAMES = [name for name in ContractForm.model_fields if name != "source_text"]
DATE_FIELDS = {"request_date", "desired_due_date", "received_date"}
ALLOWED_COUNTERPARTY_TYPES = {
    "民間",
    "大学",
    "先生（個人）",
    "国等・独立行政法人等",
    "その他",
}
ALLOWED_CONTRACT_FORMS = {"当社書式", "相手書式"}
PROMPT_TEMPLATE = """
あなたは日本語の打ち合わせメモから契約申請フォームの情報を抽出するアシスタントです。
出力はJSONのみで、余分な文章やマークダウンを含めないでください。
全てのキーを含む "form" オブジェクトを生成し、値が不明な場合は null を設定します。

必須のJSON構造:
{{
  "form": {{
    "request_date": "YYYY-MM-DD" または null,
    "desired_due_date": "YYYY-MM-DD" または null,
    "requester_department": 文字列または null,
    "requester_manager": 文字列または null,
    "requester_staff": 文字列または null,
    "project_name": 文字列または null,
    "activity_purpose": 文字列または null,
    "activity_start": 文字列または null,
    "target_item_name": 文字列または null,
    "deliverables": 文字列または null,
    "counterparty_name": 文字列または null,
    "counterparty_address": 文字列または null,
    "counterparty_type": 文字列または null,
    "contract_form": 文字列または null,
    "related_contracts": 文字列または null,
    "contract_category": 文字列または null,
    "procedure": 文字列または null,
    "cost_burden": 文字列または null,
    "restrictions": 文字列または null,
    "notes": 文字列または null,
    "amount_jpy": 整数または null,
    "our_activity_summary": 文字列または null,
    "our_productization_summary": 文字列または null,
    "their_activity_summary": 文字列または null,
    "their_productization_summary": 文字列または null,
    "received_date": "YYYY-MM-DD" または null,
    "case_number": 文字列または null
  }}
}}

制約:
- 日付フィールドは必ずYYYY-MM-DD形式で出力してください。
- "amount_jpy" は円単位の整数で出力してください (例: 3500000)。
- "counterparty_type" は ["民間","大学","先生（個人）","国等・独立行政法人等","その他"] のいずれか。
- "contract_form" は ["当社書式","相手書式"] のいずれか。
- 箇条書きなど複数の記述は文脈を保った文字列にまとめてください。
- 不明な情報を推測せず、見つからない場合は null としてください。

入力テキスト:
{conversation}
"""


def try_parse_date(text: str):
    """Try parsing various Japanese/ISO date strings into date objects."""

    candidates = re.findall(
        r"(\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日)",
        text,
    )
    if candidates:
        for candidate in candidates:
            try:
                return parser.parse(candidate).date()
            except Exception:  # pragma: no cover - dateutil handles most cases
                continue
    return None


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
        logger.exception("Gemini extraction failed: %%s", exc)
        fallback = _extract_with_regex(text)
        fallback["error"] = (
            "Gemini抽出でエラーが発生したため、正規表現ベースの抽出結果を表示しています。"
        )
        return fallback


def _extract_with_gemini(text: str) -> Dict[str, Any]:
    payload = _call_gemini(text)
    raw_form = payload.get("form", {})
    if not isinstance(raw_form, dict):
        raise ValueError("Gemini response did not include a valid 'form' object")

    form = _coerce_form(raw_form)
    _, missing = validate_form(form)
    return {"form": form.model_dump(exclude_none=True), "missing_fields": missing}


def _extract_with_regex(text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    source = text or ""

    amount_match = re.search(r"(\d{1,3}(?:,\d{3})*|\d+)\s*万円", source)
    if amount_match:
        data["amount_jpy"] = normalize_amount_jpy(amount_match.group(1) + "万円")
    else:
        amount_match = re.search(r"(\d{1,3}(?:,\d{3})*|\d+)\s*円", source)
        if amount_match:
            data["amount_jpy"] = normalize_amount_jpy(amount_match.group(1) + "円")

    project = re.search(r"(案件名|テーマ)[:：]?\s*([^\n]+)", source)
    if project:
        data["project_name"] = project.group(2).strip()

    counterparty = re.search(r"(相手先|取引先|カウンターパーティ|会社名)[:：]?\s*([^\n]+)", source)
    if counterparty:
        data["counterparty_name"] = counterparty.group(2).strip()

    address = re.search(r"(所在地|住所)[:：]?\s*([^\n]+)", source)
    if address:
        data["counterparty_address"] = address.group(2).strip()

    if "当社書式" in source:
        data["contract_form"] = "当社書式"
    if "相手書式" in source or "相手先書式" in source:
        data["contract_form"] = "相手書式"

    if "大学" in source:
        data["counterparty_type"] = "大学"
    elif "独立行政法人" in source or "国立" in source or "省庁" in source:
        data["counterparty_type"] = "国等・独立行政法人等"
    elif "先生" in source or "個人" in source:
        data["counterparty_type"] = "先生（個人）"
    else:
        data.setdefault("counterparty_type", "民間")

    parsed_date = try_parse_date(source)
    if parsed_date:
        data["request_date"] = parsed_date

    activity = re.search(r"(目的|活動目的)[:：]?\s*([^\n]+)", source)
    if activity:
        data["activity_purpose"] = activity.group(2).strip()

    start = re.search(r"(開始|開始時期|実施時期)[:：]?\s*([^\n]+)", source)
    if start:
        data["activity_start"] = start.group(2).strip()

    deliverable = re.search(r"(引渡物|成果物)[:：]?\s*([^\n]+)", source)
    if deliverable:
        data["deliverables"] = deliverable.group(2).strip()

    case_number = re.search(r"案件番号[:：]?\s*([A-Za-z0-9\-\[\]]+)", source)
    if case_number:
        data["case_number"] = case_number.group(1).strip()

    form = _coerce_form(data)
    _, missing = validate_form(form)
    return {"form": form.model_dump(exclude_none=True), "missing_fields": missing}


def _coerce_form(raw_form: Dict[str, Any]) -> ContractForm:
    cleaned = _normalize_form_payload(raw_form)
    try:
        return ContractForm(**cleaned)
    except ValidationError as exc:
        for error in exc.errors():
            loc = error.get("loc") or []
            field = loc[0] if loc else None
            if isinstance(field, str):
                cleaned.pop(field, None)
        try:
            return ContractForm(**cleaned)
        except ValidationError as second_exc:  # pragma: no cover - unexpected schema drift
            raise ValueError("正規化後のデータをフォームに変換できませんでした") from second_exc


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
            value = value.strip()
            if not value:
                continue
        if key in DATE_FIELDS and isinstance(value, str):
            parsed_date = try_parse_date(value)
            if parsed_date:
                value = parsed_date
        if key == "amount_jpy":
            if isinstance(value, str):
                value = normalize_amount_jpy(value)
            elif isinstance(value, float):
                value = int(value)
            elif not isinstance(value, int):
                continue
        if key == "counterparty_type" and value not in ALLOWED_COUNTERPARTY_TYPES:
            continue
        if key == "contract_form" and value not in ALLOWED_CONTRACT_FORMS:
            continue
        if value is not None:
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
        raise GeminiConfigError(
            ".streamlit/secrets.toml に gemini_api_key を設定してください。"
        )

    return api_key


@lru_cache(maxsize=1)
def _get_client():
    api_key = _get_api_key()
    return genai.Client(api_key=api_key)
