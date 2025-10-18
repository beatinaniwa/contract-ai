from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Iterable, Tuple

import streamlit as st
import yaml

from models.schemas import ContractForm
from services.audit import save_audit_log
from services.basic_auth import require_basic_auth
from services.csv_writer import write_csv
from services.extractor import extract_contract_form, update_form_with_followups
from services.text_loader import load_text_from_bytes
from services.validator import validate_form

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING = os.path.join(BASE_DIR, "mappings", "csv_mapping.yaml")
SAMPLE_INPUT = os.path.join(BASE_DIR, "sample_data", "example_input.txt")

FORM_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("affiliation", "所属(部署名まで)", "text_input"),
    ("target_product", "対象商材", "text_input"),
    ("activity_background", "活動背景・目的", "text_area"),
    ("counterparty_relationship", "相手方との関係・既締結の関連契約など", "text_area"),
    ("activity_details", "活動内容", "text_area"),
)
FIELD_LABELS: Dict[str, str] = {field: label for field, label, _ in FORM_FIELDS}
MAX_FOLLOW_UP_ROUNDS = 2


def _ensure_widget_defaults() -> None:
    st.session_state.setdefault("source_text", "")
    st.session_state.setdefault("source_text_widget", "")
    st.session_state.setdefault("uploaded_file_digest", None)
    st.session_state.setdefault("extracted", {"form": {}, "missing_fields": []})
    st.session_state.setdefault("follow_up_questions", [])
    st.session_state.setdefault("follow_up_round", 0)
    st.session_state.setdefault("extract_error", None)
    for field, _label, _widget in FORM_FIELDS:
        st.session_state.setdefault(f"{field}_widget", "")


def _apply_extracted_form(form_values: Dict[str, Any]) -> None:
    for field, _label, _widget in FORM_FIELDS:
        value = form_values.get(field)
        st.session_state[f"{field}_widget"] = str(value).strip() if value else ""


def _load_mapping_labels() -> Dict[str, str]:
    try:
        with open(MAPPING, "r", encoding="utf-8") as f_yaml:
            data = yaml.safe_load(f_yaml) or {}
        fields = data.get("fields", {})
        return {str(key): str(value) for key, value in fields.items()}
    except Exception:
        return {}


def _labels_for_missing(keys: Iterable[str]) -> Iterable[str]:
    mapping = _load_mapping_labels()
    for key in keys:
        yield mapping.get(key, key)


def _load_sample_text() -> str:
    if not os.path.exists(SAMPLE_INPUT):
        return ""
    with open(SAMPLE_INPUT, "r", encoding="utf-8") as f_txt:
        return f_txt.read().strip()


st.set_page_config(page_title="契約書作成アシスタント", layout="wide")
require_basic_auth()

_ensure_widget_defaults()

pending_updates = st.session_state.pop("pending_form_updates", None)
pending_missing = st.session_state.pop("pending_missing_fields", None)
pending_follow = st.session_state.pop("pending_follow_up_questions", None)
pending_clear_keys = st.session_state.pop("pending_clear_follow_up_keys", None)
pending_round = st.session_state.pop("pending_follow_up_round", None)
follow_up_feedback_data = st.session_state.pop("follow_up_update_feedback", None)
follow_up_explanation_data = st.session_state.pop("pending_follow_up_explanation", None)

if isinstance(pending_updates, dict):
    _apply_extracted_form(pending_updates)
    extracted_state = st.session_state.setdefault("extracted", {"form": {}, "missing_fields": []})
    extracted_state["form"] = pending_updates

if isinstance(pending_missing, list):
    st.session_state.setdefault("extracted", {"form": {}, "missing_fields": []})
    st.session_state["extracted"]["missing_fields"] = pending_missing

if pending_follow is not None:
    st.session_state["follow_up_questions"] = pending_follow

if pending_clear_keys:
    for key in pending_clear_keys:
        st.session_state[key] = ""

if pending_round is not None:
    st.session_state["follow_up_round"] = pending_round

st.markdown(
    """
    <style>
    div.block-container {
        max-width: 900px;
        margin: 0 auto;
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("契約書作成アシスタント")

st.subheader("元テキスト")
uploaded_file = st.file_uploader(
    "資料をアップロード（txt / md / pdf）",
    type=["txt", "md", "markdown", "pdf"],
    accept_multiple_files=False,
)
if uploaded_file is not None:
    data = uploaded_file.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if digest != st.session_state.get("uploaded_file_digest"):
        try:
            text = load_text_from_bytes(data, uploaded_file.name)
        except ValueError as exc:
            st.error(f"ファイルの読み込みに失敗しました: {exc}")
        else:
            st.session_state["source_text"] = text
            st.session_state["source_text_widget"] = text
            st.session_state["uploaded_file_digest"] = digest
            st.success("ファイルを読み込みました。")

if st.button("サンプル入力を読み込む", use_container_width=True):
    sample_text = _load_sample_text()
    if sample_text:
        st.session_state["source_text"] = sample_text
        st.session_state["source_text_widget"] = sample_text
        st.info("サンプルテキストを読み込みました。")
    else:
        st.warning("サンプルテキストが見つかりませんでした。")

source_text = st.text_area(
    "AI抽出に使用するテキスト",
    key="source_text_widget",
    height=320,
    placeholder="打ち合わせメモや案件の背景を貼り付けてください。",
)
st.session_state["source_text"] = source_text

disabled_extract = not source_text.strip()
if st.button(
    "AIでフォームを自動入力",
    use_container_width=True,
    disabled=disabled_extract,
    type="primary",
):
    with st.spinner("Geminiから情報を抽出しています…"):
        result = extract_contract_form(source_text)
    st.session_state["extracted"] = result
    st.session_state["extract_error"] = result.get("error")
    st.session_state["follow_up_questions"] = result.get("follow_up_questions", [])
    st.session_state["follow_up_round"] = 1 if st.session_state["follow_up_questions"] else 0
    _apply_extracted_form(result.get("form", {}))

extracted = st.session_state.get("extracted", {})

st.subheader("フォーム入力")
for field, label, widget_type in FORM_FIELDS:
    key = f"{field}_widget"
    if widget_type == "text_input":
        st.text_input(label, key=key)
    else:
        st.text_area(label, key=key, height=160)

submitted = st.button("CSV出力", type="primary", use_container_width=True)
if submitted:
    form_payload = {
        field: st.session_state.get(f"{field}_widget") or None for field, _, _ in FORM_FIELDS
    }
    cf = ContractForm(
        **form_payload,
        source_text=st.session_state.get("source_text", ""),
    )
    ok, missing = validate_form(cf)
    if not ok:
        labels = ", ".join(_labels_for_missing(missing))
        st.error(f"必須項目を入力してください: {labels}")
    else:
        out_dir = os.path.join(os.getcwd(), "outputs")
        out_path = write_csv(cf.model_dump(), MAPPING, out_dir=out_dir)
        st.success("CSVを生成しました。下記からダウンロードできます。")
        with open(out_path, "rb") as f_csv:
            st.download_button(
                "CSVをダウンロード",
                data=f_csv,
                file_name=os.path.basename(out_path),
                mime="text/csv",
            )
        audit_path = save_audit_log(
            cf.model_dump(),
            st.session_state.get("source_text", ""),
            out_path,
            out_dir=out_dir,
        )
        st.caption(f"監査ログを保存しました: {os.path.basename(audit_path)}")

follow_up_questions = st.session_state.get("follow_up_questions") or []
current_follow_up_round = int(st.session_state.get("follow_up_round", 0))
if follow_up_questions and current_follow_up_round <= 0:
    current_follow_up_round = 1
follow_up_feedback_message = follow_up_feedback_data
follow_up_explanation = follow_up_explanation_data if isinstance(follow_up_explanation_data, dict) else None

if follow_up_questions and current_follow_up_round <= MAX_FOLLOW_UP_ROUNDS:
    st.subheader("追加で確認したい点")
    st.caption(
        f"第{current_follow_up_round}ラウンド（最大{MAX_FOLLOW_UP_ROUNDS}ラウンド）。"
        "追加入力した回答をフォームへ反映するには、下部のボタンを押してください。"
    )
    answers_meta: list[tuple[str, str]] = []
    for idx, question in enumerate(follow_up_questions[:5], start=1):
        if isinstance(question, str):
            text = question
        elif isinstance(question, dict):
            text = str(question.get("question", ""))
        else:
            text = str(question)
        st.markdown(f"**Q{idx}. {text}**")
        answer_key = f"follow_up_answer_{idx}"
        st.text_area(
            f"回答{idx}",
            key=answer_key,
            height=80,
            placeholder="必要があればここに回答内容をメモしてください。",
            label_visibility="collapsed",
        )
        answers_meta.append((text, answer_key))

    if st.button("回答をフォームに反映", use_container_width=True):
        answered_pairs = []
        for question_text, answer_key in answers_meta:
            answer_text = str(st.session_state.get(answer_key, "") or "").strip()
            if answer_text:
                answered_pairs.append({"question": question_text, "answer": answer_text})

        if not answered_pairs:
            st.warning("回答が入力されていません。")
        else:
            current_form_snapshot = {
                field: st.session_state.get(f"{field}_widget", "") or ""
                for field, _, _ in FORM_FIELDS
            }
            update_result = update_form_with_followups(
                st.session_state.get("source_text", ""),
                current_form_snapshot,
                answered_pairs,
                current_round=current_follow_up_round or 1,
                max_rounds=MAX_FOLLOW_UP_ROUNDS,
            )
            updated_form = update_result.get("form", current_form_snapshot)
            cf_after = ContractForm(
                **{field: (updated_form.get(field) or None) for field, _, _ in FORM_FIELDS}
            )
            _, missing_after = validate_form(cf_after)

            new_follow_ups = update_result.get("follow_up_questions") or []
            explanation = update_result.get("explanation")
            next_round = int(update_result.get("next_round", current_follow_up_round))
            max_rounds_reached = bool(update_result.get("max_rounds_reached"))

            st.session_state["pending_form_updates"] = updated_form
            st.session_state["pending_missing_fields"] = missing_after
            st.session_state["pending_follow_up_questions"] = new_follow_ups
            st.session_state["pending_clear_follow_up_keys"] = [key for _, key in answers_meta]
            st.session_state["pending_follow_up_round"] = next_round
            if isinstance(explanation, dict):
                st.session_state["pending_follow_up_explanation"] = explanation
            else:
                st.session_state["pending_follow_up_explanation"] = None

            if update_result.get("error"):
                st.session_state["follow_up_update_feedback"] = (
                    "warning",
                    f"Geminiを利用できなかったため簡易的に反映しました: {update_result['error']}",
                )
            else:
                if new_follow_ups:
                    message = "回答内容をフォームに反映しました。次の確認項目をご確認ください。"
                else:
                    if max_rounds_reached or next_round >= MAX_FOLLOW_UP_ROUNDS:
                        message = (
                            f"回答内容をフォームに反映しました。追加の確認は上限の{MAX_FOLLOW_UP_ROUNDS}ラウンドまでです。"
                        )
                    else:
                        message = "回答内容をフォームに反映しました。追加の確認はありません。"
                st.session_state["follow_up_update_feedback"] = (
                    "success",
                    message,
                )

            st.rerun()

if follow_up_feedback_message:
    if isinstance(follow_up_feedback_message, (list, tuple)) and len(follow_up_feedback_message) >= 2:
        status, message = follow_up_feedback_message[0], follow_up_feedback_message[1]
    else:
        status, message = "info", str(follow_up_feedback_message)
    if status == "success":
        st.success(message)
    elif status == "warning":
        st.warning(message)
    else:
        st.info(message)
    if follow_up_explanation:
        with st.expander("反映内容の判断理由", expanded=False):
            for field, info in follow_up_explanation.items():
                if not isinstance(info, dict):
                    continue
                action = info.get("action", "unknown")
                reason = info.get("reason", "")
                label = FIELD_LABELS.get(field, field)
                action_label = "更新" if action == "updated" else "変更なし"
                st.write(f"- {label}: {action_label} — {reason}")

extract_error = st.session_state.get("extract_error")
if extract_error:
    st.info(extract_error)

extracted = st.session_state.get("extracted", {})
missing_fields = extracted.get("missing_fields") or []
if missing_fields:
    labels = ", ".join(_labels_for_missing(missing_fields))
    st.warning(f"未入力の可能性がある項目: {labels}")
elif extracted.get("form"):
    st.success("AI抽出結果をフォームに反映しました。")
