import hashlib
import difflib
import os
from datetime import date as _dt_date
from typing import Literal, cast

import streamlit as st
import re
import yaml
from typing import List, Dict

from models.schemas import ContractForm
from services.audit import save_audit_log
from services.csv_writer import write_csv
from services.extractor import extract_contract_form
from services.extractor import update_contract_sections_with_gemini
from services.extractor import gemini_healthcheck
from services.text_loader import load_text_from_bytes
from services.validator import validate_form
from services.desired_contract import summarize_desired_contract


def _strip_desired_titles(text: str) -> str:
    """Normalize desired_contract text for UI by shortening section titles."""
    if not text:
        return text
    title_patterns = [
        # 1. / 2. variations
        re.compile(r"^(?:財活動上|知財活動上)の目論見[（(].*[）)]$"),
        re.compile(r"^(?:当社の)?知財活動上の目論見[（(].*[）)]$"),
        re.compile(r"^(?:(?:相手方|相手|先方)の)?知財活動上の目論見[（(].*[）)]$"),
        # 2. canonical title
        re.compile(r"^生じ得る知財[（(].*[）)]とその性質[（(].*[）)]$"),
        # 3. / 4. titles
        re.compile(r"^上記2\.\s*に関する事業上の実施や許諾の内容[（(].*[）)]$"),
        re.compile(r"^上記1\.\s*および2\.\s*から生じ得る上記3\.\s*や知財上のリスク[（(].*[）)]$"),
    ]
    out_lines: list[str] = []
    for ln in text.splitlines():
        m = re.match(r"^\s*([1-4])\.\s*(.*)$", ln)
        if m:
            num = m.group(1)
            rest = m.group(2).strip()
            if any(pat.match(rest) for pat in title_patterns):
                out_lines.append(f"{num}. ")
                continue
        out_lines.append(ln)
    return "\n".join(out_lines)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING = os.path.join(BASE_DIR, "mappings", "csv_mapping.yaml")

st.set_page_config(page_title="契約書作成アシスタント", layout="wide")
st.title("契約書作成アシスタント")

if "source_text_widget" not in st.session_state:
    st.session_state["source_text_widget"] = st.session_state.get("source_text", "")

st.session_state.setdefault("uploaded_file_digest", None)

# 回答/抽出反映のための保留バッファを安全に適用
# - 同一ラン内に既にユーザが編集したキーは上書きしない（人手編集を優先）
# - AIが最後に適用した値（ベースライン）と現値が一致する場合のみ更新
pending_updates = st.session_state.pop("pending_widget_updates", None)
ai_baseline = st.session_state.setdefault("ai_baseline", {})
st.session_state.setdefault("ui_locked", False)
st.session_state.setdefault("ui_busy_message", "")
st.session_state.setdefault("qa_task_pending", False)
st.session_state.setdefault("qa_task", None)
st.session_state.setdefault("qa_round_tag", 0)


def _normalize_widget_value(key: str, value):
    if key == "desired_contract_widget" and isinstance(value, str):
        return _strip_desired_titles(value)
    return value


def _apply_if_not_modified(key: str, value):
    if value is None:
        return
    normalized = _normalize_widget_value(key, value)
    if key not in st.session_state:
        st.session_state[key] = normalized
        ai_baseline[key] = normalized
        return
    current = st.session_state.get(key)
    base = ai_baseline.get(key)
    if base is None or current == base:
        st.session_state[key] = normalized
        ai_baseline[key] = normalized


if isinstance(pending_updates, dict):
    for k, v in pending_updates.items():
        _apply_if_not_modified(k, v)
    # 反映が終わったのでロック解除 & メッセージ消去
    st.session_state["ui_locked"] = False
    st.session_state["ui_busy_message"] = ""

# フォーム操作の有効/無効フラグ
ui_disabled = bool(st.session_state.get("ui_locked", False))

## グレーアウトのオーバーレイは無効化（要望により一旦撤回）


# ---- Q&A処理（背景実行用）: 送信後の次ラン先頭で実行し、完了したら再描画 ----
def _process_qa_task():
    task = st.session_state.get("qa_task") or {}
    answered_for_model = task.get("answered_qas_model") or task.get("answered_qas", [])
    answered_meta = task.get("answered_qas_meta") or task.get("answered_qas", [])
    remaining_questions = task.get("remaining_questions", [])
    source_text = task.get("source_text", "")
    base_dc = task.get("base_dc", "") or summarize_desired_contract(source_text)[0]
    our_summary = task.get("our_summary", "")
    their_summary = task.get("their_summary", "")
    round_no = int(task.get("round_no", 0))
    form_data = task.get("form_data", {}) or {}

    # 初期状態
    updated_dc = base_dc
    explanation_for_ui: Dict[str, Dict[str, str]] | None = None
    engine_status: str = "skipped"
    gemini_error: str | None = None
    model_follow_ups: List[str] = []

    try:
        if answered_for_model:
            updated = update_contract_sections_with_gemini(
                source_text=source_text,
                current_values={
                    "desired_contract": base_dc or "",
                    "our_overall_summary": our_summary or "",
                    "their_overall_summary": their_summary or "",
                },
                qa=answered_for_model,
            )
            engine_status = "gemini"
            updated_dc = updated.get("desired_contract", base_dc) or base_dc
            our_summary = updated.get("our_overall_summary", our_summary) or our_summary
            their_summary = (
                updated.get("their_overall_summary", their_summary) or their_summary
            )
            maybe_expl = updated.get("explanation")
            if isinstance(maybe_expl, dict):
                explanation_for_ui = maybe_expl  # type: ignore[assignment]
            fus_raw = updated.get("follow_up_questions")
            if isinstance(fus_raw, list):
                for item in fus_raw:
                    qtxt = item.get("question", "") if isinstance(item, dict) else str(item)
                    if qtxt and qtxt.strip():
                        model_follow_ups.append(qtxt.strip())
                model_follow_ups = model_follow_ups[:5]
    except Exception as exc:
        gemini_error = f"Gemini の呼び出しに失敗: {exc.__class__.__name__}: {exc}"
        # 簡易フォールバック：どの章か推定して回答を追記
        def _map_question_to_section(question: str) -> int | None:
            if "取り扱い方針" in question or "目標は何ですか" in question:
                return 1
            if "追加で重視" in question or "ノウハウ帰属" in question:
                return 2
            if "実施・許諾の対象と範囲" in question:
                return 3
            if "想定リスク" in question or "FTO" in question:
                return 4
            return None

        def _parse_sections(dc_text: str) -> Dict[int, List[str]]:
            sections: Dict[int, List[str]] = {1: [], 2: [], 3: [], 4: []}
            if not dc_text:
                return sections
            lines = dc_text.splitlines()
            current: int | None = None
            for ln in lines:
                m = re.match(r"^\s*([1-4])\.\s*(.*)$", ln)
                if m:
                    current = int(m.group(1))
                    inline = m.group(2).strip()
                    if inline:
                        sections[current].append(inline)
                    continue
                if current and ln.lstrip().startswith("-"):
                    sections[current].append(ln.lstrip()[1:].strip())
            return sections

        def _rebuild_desired_contract(sections: Dict[int, List[str]]) -> str:
            titles = {
                1: "1. 財活動上の目論見（知財創出/権利化/ライセンス/知財売買/知財保証/・・・）",
                2: "2. 生じ得る知財（発明/意匠/商標/ソフト等）とその性質（単独/共有）",
                3: "3. 上記2. に関する事業上の実施や許諾の内容（当社製品が実施品/当社と取引後の相手や顧客の製品が実施品/取引の前後に関係なく双方の製品が実施品/・・・）",
                4: "4. 上記1. および2. から生じ得る上記3. や知財上のリスク（自己実施上の支障/第三者による実施/コンタミによる出願上の支障/第三者からの権利行使/実施料の発生/・・・）",
            }
            chunks: List[str] = []
            for i in (1, 2, 3, 4):
                bullets = sections.get(i, []) or ["記載なし"]
                chunk = titles[i] + "\n- " + "\n- ".join(bullets)
                chunks.append(chunk)
            return "\n\n".join(chunks)

        sections = _parse_sections(base_dc)
        for qa in answered_meta:
            q = qa.get("question", "")
            ans = qa.get("answer", "")
            target = qa.get("target")
            sec = None
            if target == "desired_contract" or target is None:
                sec = _map_question_to_section(q)
                if sec:
                    sections.setdefault(sec, [])
                    if ans not in sections[sec]:
                        sections[sec].append(ans)
            if target == "our_overall_summary":
                our_summary = (our_summary + ("\n" if our_summary else "") + ans).strip()
            elif target == "their_overall_summary":
                their_summary = (
                    their_summary + ("\n" if their_summary else "") + ans
                ).strip()
            else:
                if any(key in ans for key in ("当社", "弊社")):
                    our_summary = (our_summary + ("\n" if our_summary else "") + ans).strip()
                if any(key in ans for key in ("相手", "先方", "相手方", "相手先")):
                    their_summary = (
                        their_summary + ("\n" if their_summary else "") + ans
                    ).strip()
        updated_dc = _rebuild_desired_contract(sections)
        explanation_for_ui = {
            "desired_contract": {
                "action": "updated" if updated_dc != base_dc else "unchanged",
                "reason": "回答内容を章別に追記（Gemini未使用のフォールバック）"
                if updated_dc != base_dc
                else "回答が空または変更不要のため維持（フォールバック）",
            },
            "our_overall_summary": {
                "action": "updated"
                if form_data.get("our_overall_summary", "") != our_summary
                else "unchanged",
                "reason": "回答（当社/弊社含む）を反映"
                if form_data.get("our_overall_summary", "") != our_summary
                else "変更不要",
            },
            "their_overall_summary": {
                "action": "updated"
                if form_data.get("their_overall_summary", "") != their_summary
                else "unchanged",
                "reason": "回答（相手/先方 等）を反映"
                if form_data.get("their_overall_summary", "") != their_summary
                else "変更不要",
            },
        }
        engine_status = "fallback"

    # エクスポート用のフォームとウィジェット適用
    st.session_state.setdefault("extracted", {"form": {}, "missing_fields": []})
    st.session_state["extracted"].setdefault("form", {})
    st.session_state["extracted"]["form"]["desired_contract"] = updated_dc
    if our_summary:
        st.session_state["extracted"]["form"]["our_overall_summary"] = our_summary
    if their_summary:
        st.session_state["extracted"]["form"]["their_overall_summary"] = their_summary

    # Before/After の保存（表示用）
    before_vals = {
        "desired_contract": base_dc or "",
        "our_overall_summary": form_data.get("our_overall_summary", "") or "",
        "their_overall_summary": form_data.get("their_overall_summary", "") or "",
    }
    after_vals = {
        "desired_contract": updated_dc or "",
        "our_overall_summary": our_summary or "",
        "their_overall_summary": their_summary or "",
    }
    st.session_state["qa_diff_before"] = before_vals
    st.session_state["qa_diff_after"] = after_vals

    # UIウィジェットへ反映は次ラン先頭で（生成前に入れるため）
    st.session_state["pending_widget_updates"] = {
        "desired_contract_widget": updated_dc,
        "our_overall_summary_widget": our_summary,
        "their_overall_summary_widget": their_summary,
    }

    # 次ラウンドの質問生成（最大5件）
    def _sections_status(dc_text: str) -> Dict[int, bool]:
        # 章の有無を簡易判定
        lines = [ln.strip() for ln in (dc_text or "").splitlines()]
        present = {1: False, 2: False, 3: False, 4: False}
        current = None
        for ln in lines:
            m = re.match(r"^([1-4])\.\s*", ln)
            if m:
                current = int(m.group(1))
                continue
            if current and ln.startswith("-") and ln[1:].strip() and ln[1:].strip() != "記載なし":
                present[current] = True
        return present

    def _build_questions_for_missing(sections_ok: Dict[int, bool]) -> List[str]:
        q_list: List[str] = []
        if not sections_ok.get(1, False):
            q_list.append(
                "（どんな契約にしたいか補足）知財の取り扱い方針（創出/権利化/ライセンス/売買/保証）のうち、今回の目標は何ですか？"
            )
        if not sections_ok.get(2, False):
            q_list.append(
                "（どんな契約にしたいか補足）知財面で追加で重視したい事項（例: ノウハウ帰属、譲渡可否、保証範囲）がありますか？"
            )
        if not sections_ok.get(3, False):
            q_list.append(
                "（どんな契約にしたいか補足）実施・許諾の対象と範囲（当社製品/相手製品/双方、地域・期間、サブライセンス可否）を教えてください。"
            )
        if not sections_ok.get(4, False):
            q_list.append(
                "（どんな契約にしたいか補足）想定リスク（自己実施の支障、第三者権利、コンタミ、実施料 等）があれば列挙してください。"
            )
        if not (our_summary or "").strip():
            q_list.append("（概要補足）当社側の要点を一言で教えてください。")
        if not (their_summary or "").strip():
            q_list.append("（概要補足）相手側の要点を一言で教えてください。")
        return q_list

    sections_ok = _sections_status(updated_dc)
    if model_follow_ups:
        next_candidates = remaining_questions + model_follow_ups
    else:
        next_candidates = remaining_questions + _build_questions_for_missing(sections_ok)
    seen: set[str] = set()
    next_questions: List[Dict[str, str]] = []
    for item in next_candidates:
        if isinstance(item, dict):
            qtext = item.get("question", "")
            qtarget = item.get("target")
        else:
            qtext = str(item)
            qtarget = None
        normalized_text = qtext.strip()
        if not normalized_text or normalized_text in seen:
            continue
        seen.add(normalized_text)
        entry: Dict[str, str] = {"question": normalized_text}
        if qtarget:
            entry["target"] = qtarget
        next_questions.append(entry)
        if len(next_questions) >= 5:
            break

    if next_questions and round_no < 1:
        st.session_state["extracted"]["follow_up_questions"] = next_questions
        st.session_state["qa_round"] = round_no + 1
        st.session_state["qa_round_tag"] = st.session_state.get("qa_round_tag", 0) + 1
        for key in list(st.session_state.keys()):
            if key.startswith("qa_answer_"):
                st.session_state.pop(key, None)
    else:
        st.session_state["extracted"].pop("follow_up_questions", None)
        st.session_state["qa_round"] = 0
        st.session_state["qa_round_tag"] = 0
        for key in list(st.session_state.keys()):
            if key.startswith("qa_answer_"):
                st.session_state.pop(key, None)

    engine_label = (
        "Gemini 2.5 Pro"
        if engine_status == "gemini"
        else "Gemini未使用のフォールバック"
        if engine_status == "fallback"
        else "Gemini未実行（回答未入力）"
    )
    st.session_state["qa_feedback"] = (
        "success",
        f"{engine_label}で回答を吟味し、フォームへ反映しました。",
    )
    st.session_state["qa_update_explanation"] = explanation_for_ui or {}
    st.session_state["qa_update_engine"] = engine_status

    # タスク完了 → 次ランで適用される
    st.session_state["qa_task_pending"] = False
    # 継続してロック保持（適用完了まで）
    st.session_state["ui_locked"] = True
    st.session_state["ui_busy_message"] = "AIの回答結果を反映しています…"
    try:
        getattr(st, "rerun")()
    except Exception:
        getattr(st, "experimental_rerun", lambda: None)()


if st.session_state.get("qa_task_pending"):
    with st.spinner(st.session_state.get("ui_busy_message") or "AIの回答結果を反映しています…"):
        _process_qa_task()

col_left, col_right = st.columns([2, 1])

with col_right:
    st.header("AIサポート")
    if ui_disabled:
        st.info("AIの回答結果を反映中です。しばらくお待ちください…")
    uploaded_file = st.file_uploader(
        "案件の概要や条件のファイルをアップロード",
        type=["pdf", "txt"],
        accept_multiple_files=False,
        disabled=ui_disabled,
    )

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        file_digest = hashlib.sha256(file_bytes).hexdigest()
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
        if st.session_state.get("uploaded_file_digest") != file_digest:
            try:
                loaded_text = load_text_from_bytes(file_bytes, uploaded_file.name)
            except ValueError as exc:
                st.session_state["extract_feedback"] = ("error", str(exc))
            else:
                st.session_state["source_text"] = loaded_text
                st.session_state["source_text_widget"] = loaded_text
                st.session_state["uploaded_file_digest"] = file_digest
                st.session_state["extract_feedback"] = (
                    "success",
                    f"{uploaded_file.name} からテキストを読み込みました。",
                )

    src_text = st.text_area(
        "案件の概要や条件を自由に入力してください。",
        height=260,
        key="source_text_widget",
        disabled=ui_disabled,
    )
    hc_col1, hc_col2 = st.columns([1, 1])
    with hc_col1:
        if st.button("Gemini接続チェック", use_container_width=True, disabled=ui_disabled):
            ok, msg = gemini_healthcheck()
            if ok:
                st.success("Gemini 2.5 Pro への接続はOKです。")
            else:
                st.error(f"Gemini接続に問題があります: {msg}")
    if st.button("AIでフォームに反映", type="primary", use_container_width=True, disabled=ui_disabled):
        result = extract_contract_form(src_text)
        st.session_state["extracted"] = result
        st.session_state["source_text"] = src_text
        st.session_state["qa_round"] = 0
        st.session_state["qa_round_tag"] = 0
        for key in list(st.session_state.keys()):
            if key.startswith("qa_answer_"):
                st.session_state.pop(key, None)

        # 3欄のウィジェットキーへも反映（次の rerun の先頭で適用）
        form_preview = result.get("form", {}) if isinstance(result, dict) else {}
        updates: Dict[str, object] = {}
        # 3欄
        dc_val = form_preview.get("desired_contract")
        our_val = form_preview.get("our_overall_summary")
        their_val = form_preview.get("their_overall_summary")
        if isinstance(dc_val, str):
            updates["desired_contract_widget"] = dc_val
        if isinstance(our_val, str):
            updates["our_overall_summary_widget"] = our_val
        if isinstance(their_val, str):
            updates["their_overall_summary_widget"] = their_val
        # 優先拡張フィールド（人手編集を上書きしない・ベースライン比較で適用）
        rd = form_preview.get("request_date")
        if isinstance(rd, _dt_date):
            updates["request_date_widget"] = rd
        nd = form_preview.get("normal_due_date") or form_preview.get("desired_due_date")
        if isinstance(nd, _dt_date):
            updates["normal_due_date_widget"] = nd
        for text_key, widget_key in [
            ("requester_department", "requester_department_widget"),
            ("requester_manager", "requester_manager_widget"),
            ("requester_staff", "requester_staff_widget"),
            ("project_name", "project_name_widget"),
            ("activity_purpose", "activity_purpose_widget"),
            ("activity_start", "activity_start_widget"),
            ("counterparty_name", "counterparty_name_widget"),
            ("counterparty_address", "counterparty_address_widget"),
            ("counterparty_profile", "counterparty_profile_widget"),
        ]:
            val = form_preview.get(text_key)
            if isinstance(val, str):
                updates[widget_key] = val
        amt = form_preview.get("amount_jpy")
        if isinstance(amt, int):
            updates["amount_jpy_widget"] = amt
        if updates:
            st.session_state["pending_widget_updates"] = updates

        if result.get("error"):
            st.session_state["extract_feedback"] = ("warning", result["error"])
        else:
            st.session_state["extract_feedback"] = ("success", "Geminiで抽出結果を取得しました。")

        # UIを更新して、左側フォームに即時反映
        try:
            getattr(st, "rerun")()
        except Exception:
            getattr(st, "experimental_rerun", lambda: None)()


feedback = st.session_state.pop("extract_feedback", None)
if feedback:
    status, message = feedback
    if status == "success":
        st.success(message)
    elif status == "error":
        st.error(message)
    else:
        st.warning(message)

# Q&A反映のフラッシュメッセージ
qa_feedback = st.session_state.pop("qa_feedback", None)
if qa_feedback:
    qa_status, qa_message = qa_feedback
    if qa_status == "success":
        st.success(qa_message)
    elif qa_status == "error":
        st.error(qa_message)
    else:
        st.info(qa_message)


def load_vocab():
    p = os.path.join(BASE_DIR, "policies", "vocab.yaml")
    with open(p, "r", encoding="utf-8") as f_yaml:
        return yaml.safe_load(f_yaml)


vocab = load_vocab()

col_main = col_left

with col_main:
    st.subheader("フォーム（編集可）")

    if ui_disabled:
        st.info("AIの回答結果を反映中です。フォームは一時的に編集できません。")

    # 既存データの展開
    extracted = st.session_state.get("extracted", {"form": {}, "missing_fields": []})
    form_data = extracted.get("form", {})

    # 動的フォーム
    # 入力ウィジェット（フォームを使わずリアクティブに）
    # 基本情報
    def _ensure_default(key: str, default):
        if key not in st.session_state:
            normalized = _normalize_widget_value(key, default)
            st.session_state[key] = normalized
            ai_baseline[key] = normalized

    _ensure_default("request_date_widget", form_data.get("request_date") or _dt_date.today())
    _ensure_default(
        "normal_due_date_widget",
        form_data.get("normal_due_date") or form_data.get("desired_due_date") or _dt_date.today(),
    )
    request_date = st.date_input("依頼日", key="request_date_widget", disabled=ui_disabled)
    normal_due_date = st.date_input("通常納期", key="normal_due_date_widget", disabled=ui_disabled)
    _ensure_default("requester_department_widget", form_data.get("requester_department", ""))
    requester_department = st.text_input("依頼者_所属", key="requester_department_widget", disabled=ui_disabled)
    _ensure_default("requester_manager_widget", form_data.get("requester_manager", ""))
    requester_manager = st.text_input("依頼者_責任者", key="requester_manager_widget", disabled=ui_disabled)
    _ensure_default("requester_staff_widget", form_data.get("requester_staff", ""))
    requester_staff = st.text_input("依頼者_担当者", key="requester_staff_widget", disabled=ui_disabled)

    # 案件_種別（最初に追加）
    project_type_options = vocab.get("project_type", [])
    default_project_type = form_data.get("project_type")
    project_type_index = (
        (
            project_type_options.index(default_project_type)
            if default_project_type in project_type_options
            else 0
        )
        if project_type_options
        else 0
    )
    project_type = st.selectbox(
        "案件_種別", options=project_type_options or ["NDA"], index=project_type_index, disabled=ui_disabled
    )

    # 案件_国内外（2番目）
    project_domestic_foreign_options = vocab.get("project_domestic_foreign", [])
    default_pdf = form_data.get("project_domestic_foreign")
    pdf_index = (
        (
            project_domestic_foreign_options.index(default_pdf)
            if default_pdf in project_domestic_foreign_options
            else 0
        )
        if project_domestic_foreign_options
        else 0
    )
    project_domestic_foreign = st.selectbox(
        "案件_国内外",
        options=project_domestic_foreign_options or ["国内"],
        index=pdf_index,
        disabled=ui_disabled,
    )

    _ensure_default("project_name_widget", form_data.get("project_name", ""))
    project_name = st.text_input("案件_案件名", key="project_name_widget", disabled=ui_disabled)
    _ensure_default("activity_purpose_widget", form_data.get("activity_purpose", ""))
    activity_purpose = st.text_area("案件_活動目的", height=80, key="activity_purpose_widget", disabled=ui_disabled)
    _ensure_default("activity_start_widget", form_data.get("activity_start", ""))
    activity_start = st.text_input("案件_実活動時期", key="activity_start_widget", disabled=ui_disabled)

    # 契約対象品目（単一選択）
    project_target_item_options = vocab.get(
        "project_target_item", ["ハード", "ソフト", "技術", "役務", "その他"]
    )
    default_target_raw = form_data.get("project_target_item") or form_data.get("target_item_name")
    if default_target_raw in project_target_item_options:
        project_target_item_index = project_target_item_options.index(default_target_raw)
    elif default_target_raw and "その他" in project_target_item_options:
        project_target_item_index = project_target_item_options.index("その他")
    else:
        project_target_item_index = 0
    project_target_item = st.selectbox(
        "契約対象品目",
        options=project_target_item_options,
        index=project_target_item_index,
        disabled=ui_disabled,
    )

    _ensure_default("counterparty_name_widget", form_data.get("counterparty_name", ""))
    counterparty_name = st.text_input("契約相手_名称", key="counterparty_name_widget", disabled=ui_disabled)
    _ensure_default("counterparty_address_widget", form_data.get("counterparty_address", ""))
    counterparty_address = st.text_input("契約相手_所在地", key="counterparty_address_widget", disabled=ui_disabled)
    _ensure_default("counterparty_profile_widget", form_data.get("counterparty_profile", ""))
    counterparty_profile = st.text_area("契約相手_プロフィール", height=80, key="counterparty_profile_widget", disabled=ui_disabled)
    # 概要_相手区分 + 条件付き: ソリューション技術企画室への相談有無（ここで表示）
    counterparty_type_options = vocab.get("counterparty_type", [])
    default_counterparty_type = form_data.get("counterparty_type")
    ct_index = (
        (
            counterparty_type_options.index(default_counterparty_type)
            if default_counterparty_type in counterparty_type_options
            else 0
        )
        if counterparty_type_options
        else 0
    )
    counterparty_type = st.selectbox(
        "概要_相手区分",
        options=counterparty_type_options or ["民間"],
        index=ct_index,
        disabled=ui_disabled,
    )
    requires_solution_consult = counterparty_type in {
        "大学",
        "先生（個人）",
        "国等・独立行政法人等",
    }
    if requires_solution_consult:
        spo_options = vocab.get("solution_planning_office_consultation", ["未", "済"])  # fallback
        default_spo = form_data.get("solution_planning_office_consultation")
        spo_index = (
            (spo_options.index(default_spo) if default_spo in spo_options else 0)
            if isinstance(spo_options, list) and spo_options
            else 0
        )
        solution_planning_office_consultation = st.selectbox(
            "ソリューション技術企画室への相談有無",
            options=spo_options or ["未", "済"],
            index=spo_index,
            disabled=ui_disabled,
        )
    else:
        solution_planning_office_consultation = ""

    contract_form_options = vocab.get("contract_form", ["当社書式", "相手書式"])
    default_contract_form = form_data.get("contract_form")
    cf_index = (
        (
            contract_form_options.index(default_contract_form)
            if default_contract_form in contract_form_options
            else 0
        )
        if contract_form_options
        else 0
    )
    contract_form = st.selectbox("概要_契約書式", options=contract_form_options, index=cf_index, disabled=ui_disabled)
    related_contract_flag = st.selectbox(
        "概要_関連契約",
        options=vocab.get("related_contract_flag", ["該当なし", "該当あり"]),
        index=0,
        disabled=ui_disabled,
    )

    _ensure_default("amount_jpy_widget", int(form_data.get("amount_jpy", 0)))
    amount_jpy = st.number_input("概要_金額", min_value=0, step=1000, key="amount_jpy_widget", disabled=ui_disabled)

    # 開示される情報
    info_options = vocab.get(
        "disclosed_info_options",
        ["要求仕様", "関連技術情報", "図面", "サンプル"],
    )
    info_from_us: List[str] = st.multiselect(
        "概要_開示される情報_当社から",
        options=info_options,
        default=form_data.get("info_from_us", []),
        disabled=ui_disabled,
    )
    info_from_us_other = st.text_input(
        "概要_開示される情報_当社から_その他",
        value=form_data.get("info_from_us_other", ""),
        placeholder="他に開示予定があれば記入（空でも可）",
        help="選択肢にない開示事項があれば1行で記入。未入力可。",
        key="info_from_us_other",
        disabled=ui_disabled,
    )

    info_from_them: List[str] = st.multiselect(
        "概要_開示される情報_相手から",
        options=info_options,
        default=form_data.get("info_from_them", []),
        disabled=ui_disabled,
    )
    info_from_them_other = st.text_input(
        "概要_開示される情報_相手から_その他",
        value=form_data.get("info_from_them_other", ""),
        placeholder="他に相手からの開示があれば記入（空でも可）",
        help="選択肢にない相手からの開示事項があれば1行で記入。未入力可。",
        key="info_from_them_other",
        disabled=ui_disabled,
    )

    our_overall_summary_default = form_data.get("our_overall_summary")
    if not our_overall_summary_default:
        # 旧フィールドからの統合
        parts = [
            form_data.get("our_activity_summary", "").strip(),
            form_data.get("our_productization_summary", "").strip(),
        ]
        parts = [p for p in parts if p]
        our_overall_summary_default = "\n".join(parts)
    _ensure_default("our_overall_summary_widget", our_overall_summary_default or "")
    our_overall_summary = st.text_area(
        "概要_当社の契約活動概要および成果事業化概要",
        height=100,
        key="our_overall_summary_widget",
        disabled=ui_disabled,
    )

    their_overall_summary_default = form_data.get("their_overall_summary")
    if not their_overall_summary_default:
        parts = [
            form_data.get("their_activity_summary", "").strip(),
            form_data.get("their_productization_summary", "").strip(),
        ]
        parts = [p for p in parts if p]
        their_overall_summary_default = "\n".join(parts)
    _ensure_default("their_overall_summary_widget", their_overall_summary_default or "")
    their_overall_summary = st.text_area(
        "概要_相手の契約活動概要および成果事業化概要",
        height=100,
        key="their_overall_summary_widget",
        disabled=ui_disabled,
    )

    # 「どんな契約にしたいか」のガイダンス（テキストエリアの外に説明を表示）
    st.markdown(
        """
        どんな契約にしたいか（記入ガイド）

        1. 財活動上の目論見（知財創出/権利化/ライセンス/知財売買/知財保証/・・・）
        2. 生じ得る知財（発明/意匠/商標/ソフト等）とその性質（単独/共有）
        3. 上記2. に関する事業上の実施や許諾の内容（当社製品が実施品/当社と取引後の相手や顧客の製品が実施品/取引の前後に関係なく双方の製品が実施品/・・・）
        4. 上記1. および2. から生じ得る上記3. や知財上のリスク（自己実施上の支障/第三者による実施/コンタミによる出願上の支障/第三者からの権利行使/実施料の発生/・・・）
        """
    )

    # 右カラムのAI反映で raw 文字列が入った場合でも、表示前にタイトルを簡略化
    try:
        if "desired_contract_widget" in st.session_state and isinstance(
            st.session_state.get("desired_contract_widget"), str
        ):
            existing = st.session_state.get("desired_contract_widget", "")
            normalized = _strip_desired_titles(existing)
            if normalized != existing:
                st.session_state["desired_contract_widget"] = normalized
            base = ai_baseline.get("desired_contract_widget")
            if base is None or base == existing:
                ai_baseline["desired_contract_widget"] = normalized
    except Exception:
        pass

    desired_contract_default = (form_data.get("desired_contract", "") or "").strip()
    if desired_contract_default:
        desired_contract_default = _strip_desired_titles(desired_contract_default)
    else:
        desired_contract_default = "\n".join(["1. ", "", "2. ", "", "3. ", "", "4. "]) + "\n"
    _ensure_default("desired_contract_widget", desired_contract_default)

    desired_contract = st.text_area(
        "どんな契約にしたいか",
        height=300,
        help="番号に続けて内容を記入。必要に応じて各番号の下に '- ' で箇条書きも可。",
        key="desired_contract_widget",
        disabled=ui_disabled,
    )

    submitted = st.button("CSV出力", type="primary", disabled=ui_disabled)

    if submitted:
        # 旧 related_contracts 文字列からのフォールバック: 非空なら該当あり
        raw_related_flag = related_contract_flag or (
            "該当あり" if form_data.get("related_contracts") else "該当なし"
        )
        if raw_related_flag not in ("該当なし", "該当あり"):
            raw_related_flag = "該当なし"
        related_flag: Literal["該当なし", "該当あり"] = cast(
            Literal["該当なし", "該当あり"], raw_related_flag
        )
        cf = ContractForm(
            request_date=request_date or None,
            normal_due_date=normal_due_date or None,
            requester_department=requester_department or None,
            requester_manager=requester_manager or None,
            requester_staff=requester_staff or None,
            project_type=project_type or None,
            project_domestic_foreign=project_domestic_foreign or None,
            project_name=project_name or None,
            activity_purpose=activity_purpose or None,
            activity_start=activity_start or None,
            project_target_item=project_target_item or None,
            counterparty_name=counterparty_name or None,
            counterparty_address=counterparty_address or None,
            counterparty_profile=counterparty_profile or None,
            counterparty_type=counterparty_type or None,
            solution_planning_office_consultation=(solution_planning_office_consultation or None),
            contract_form=contract_form or None,
            related_contract_flag=related_flag,
            amount_jpy=amount_jpy or None,
            info_from_us=info_from_us,
            info_from_us_other=info_from_us_other,
            info_from_them=info_from_them,
            info_from_them_other=info_from_them_other,
            our_overall_summary=our_overall_summary or None,
            their_overall_summary=their_overall_summary or None,
            desired_contract=desired_contract or None,
            # 自由記述系（抽出済みの既存値があれば保持）
            contract_category=form_data.get("contract_category"),
            procedure=form_data.get("procedure"),
            cost_burden=form_data.get("cost_burden"),
            restrictions=form_data.get("restrictions"),
            notes=form_data.get("notes"),
            # 旧フィールドを残しておく（抽出プレビュー整合のため）
            desired_due_date=form_data.get("desired_due_date"),
            target_item_name=form_data.get("target_item_name"),
            deliverables=form_data.get("deliverables"),
            our_activity_summary=form_data.get("our_activity_summary"),
            our_productization_summary=form_data.get("our_productization_summary"),
            their_activity_summary=form_data.get("their_activity_summary"),
            their_productization_summary=form_data.get("their_productization_summary"),
            received_date=form_data.get("received_date"),
            case_number=form_data.get("case_number"),
            source_text=st.session_state.get("source_text", ""),
        )
        ok, missing = validate_form(cf)
        if not ok:

            def _to_japanese_labels(keys: list[str]) -> list[str]:
                try:
                    with open(MAPPING, "r", encoding="utf-8") as f_yaml:
                        mapping = yaml.safe_load(f_yaml) or {}
                    field_map = mapping.get("fields", {}) if isinstance(mapping, dict) else {}
                    return [field_map.get(k, k) for k in keys]
                except Exception:
                    return keys

            labels = _to_japanese_labels(missing)
            st.error(f"必須項目が未入力です: {', '.join(labels)}")
        else:
            out_path = write_csv(
                cf.model_dump(), MAPPING, out_dir=os.path.join(os.getcwd(), "outputs")
            )
            st.success("CSVを生成しました。")
            with open(out_path, "rb") as f_bin:
                st.download_button(
                    "CSVをダウンロード",
                    data=f_bin,
                    file_name=os.path.basename(out_path),
                    mime="text/csv",
                )

            # 監査ログ
            audit_path = save_audit_log(
                cf.model_dump(),
                st.session_state.get("source_text", ""),
                out_path,
                out_dir=os.path.join(os.getcwd(), "outputs"),
            )
            st.caption(f"監査ログを保存: {os.path.basename(audit_path)}")

    extracted_payload = st.session_state.get("extracted", {})
    follow_up = extracted_payload.get("follow_up_questions") or []
    if follow_up:
        st.subheader("追加で確認したい点 (最大5件)")
        round_no = int(st.session_state.get("qa_round", 0))
        if round_no == 0:
            st.caption("第1ラウンドの確認質問です。必要な範囲でご回答ください。")
        else:
            st.caption("第2ラウンドの確認質問です。未充足の点のみ再確認します。")
        answers: Dict[int, str] = {}
        round_tag = int(st.session_state.get("qa_round_tag", 0))
        for idx, q in enumerate(follow_up):
            q_text = q.get("question", "") if isinstance(q, dict) else str(q)
            st.markdown(f"Q{idx + 1}. {q_text}")
            ans_key = f"qa_answer_{round_tag}_{idx}"
            answers[idx] = st.text_area(
                label=f"回答{idx + 1}",
                key=ans_key,
                height=60,
                placeholder="（任意）必要十分な記載にするための補足を記入。未入力でも可。",
                disabled=ui_disabled,
            )

        def _map_question_to_section(question: str) -> int | None:
            if "取り扱い方針" in question or "目標は何ですか" in question:
                return 1
            if "追加で重視" in question or "ノウハウ帰属" in question:
                return 2
            if "実施・許諾の対象と範囲" in question:
                return 3
            if "想定リスク" in question or "FTO" in question:
                return 4
            return None

        def _parse_sections(dc_text: str) -> Dict[int, List[str]]:
            sections: Dict[int, List[str]] = {1: [], 2: [], 3: [], 4: []}
            if not dc_text:
                return sections
            lines = dc_text.splitlines()
            current = None
            for ln in lines:
                # 「N. 内容」のように番号の後に直接内容が続く場合も取り込む
                m = re.match(r"^\s*([1-4])\.\s*(.*)$", ln)
                if m:
                    current = int(m.group(1))
                    inline = m.group(2).strip()
                    if inline:
                        sections[current].append(inline)
                    continue
                if current and ln.lstrip().startswith("-"):
                    sections[current].append(ln.lstrip()[1:].strip())
            return sections

        def _rebuild_desired_contract(sections: Dict[int, List[str]]) -> str:
            titles = {
                1: "1. 財活動上の目論見（知財創出/権利化/ライセンス/知財売買/知財保証/・・・）",
                2: "2. 生じ得る知財（発明/意匠/商標/ソフト等）とその性質（単独/共有）",
                3: "3. 上記2. に関する事業上の実施や許諾の内容（当社製品が実施品/当社と取引後の相手や顧客の製品が実施品/取引の前後に関係なく双方の製品が実施品/・・・）",
                4: "4. 上記1. および2. から生じ得る上記3. や知財上のリスク（自己実施上の支障/第三者による実施/コンタミによる出願上の支障/第三者からの権利行使/実施料の発生/・・・）",
            }
            chunks: List[str] = []
            for i in (1, 2, 3, 4):
                bullets = sections.get(i, [])
                if not bullets:
                    bullets = ["記載なし"]
                chunk = titles[i] + "\n- " + "\n- ".join(bullets)
                chunks.append(chunk)
            return "\n\n".join(chunks)

        if st.button("回答を送信", type="secondary", use_container_width=True, disabled=ui_disabled):
            form_data = extracted_payload.get("form", {})
            source_text = st.session_state.get("source_text", "")
            base_dc = (
                form_data.get("desired_contract") or summarize_desired_contract(source_text)[0]
            )

            our_summary = form_data.get("our_overall_summary", "") or ""
            their_summary = form_data.get("their_overall_summary", "") or ""

            remaining_questions: List[Dict[str, str]] = []
            answered_qas_model: List[Dict[str, str]] = []
            answered_qas_meta: List[Dict[str, str]] = []
            for idx, q in enumerate(follow_up):
                if isinstance(q, dict):
                    q_text = q.get("question", "")
                    q_target = q.get("target")
                    q_obj = {k: v for k, v in q.items() if v is not None}
                else:
                    q_text = str(q)
                    q_target = None
                    q_obj = {"question": q_text}
                ans = (answers.get(idx) or "").strip()
                if not ans:
                    remaining_questions.append(q_obj)
                    continue
                answered_qas_model.append({"question": q_text, "answer": ans})
                meta = {"question": q_text, "answer": ans}
                if q_target:
                    meta["target"] = q_target
                answered_qas_meta.append(meta)

            # ロックして処理を次ラン先頭に委譲
            st.session_state["ui_locked"] = True
            st.session_state["ui_busy_message"] = "AIの回答結果を反映しています…"
            st.session_state["qa_task"] = {
                "answered_qas_model": answered_qas_model,
                "answered_qas_meta": answered_qas_meta,
                "remaining_questions": remaining_questions,
                "source_text": source_text,
                "base_dc": base_dc,
                "our_summary": our_summary,
                "their_summary": their_summary,
                "form_data": form_data,
                "round_no": int(st.session_state.get("qa_round", 0)),
            }
            st.session_state["qa_task_pending"] = True
            try:
                getattr(st, "rerun")()
            except Exception:
                getattr(st, "experimental_rerun", lambda: None)()

    expl = st.session_state.get("qa_update_explanation")
    if expl:
        engine = st.session_state.get("qa_update_engine", "gemini")
        st.subheader("回答反映の判断結果")
        if engine == "gemini":
            st.caption("Gemini 2.5 Pro による更新判断")
        elif engine == "fallback":
            st.caption("Gemini未使用のフォールバックによる更新判断")
        else:
            st.caption("Geminiは実行していません（回答未入力のため）")

        def _render_line(label: str, key: str):
            info = expl.get(key, {}) if isinstance(expl, dict) else {}
            action = info.get("action", "unknown")
            reason = info.get("reason", "")
            status = (
                "更新" if action == "updated" else "変更なし" if action == "unchanged" else "不明"
            )
            st.write(f"- {label}: {status} — {reason}")

        _render_line("どんな契約にしたいか", "desired_contract")
        _render_line("概要_当社の契約活動概要および成果事業化概要", "our_overall_summary")
        _render_line("概要_相手の契約活動概要および成果事業化概要", "their_overall_summary")

        # Before/After の視覚化（diff で強調）
        diff_before = st.session_state.get("qa_diff_before")
        diff_after = st.session_state.get("qa_diff_after")
        if isinstance(diff_before, dict) and isinstance(diff_after, dict):
            st.subheader("更新内容（差分）")
            items = [
                ("どんな契約にしたいか", "desired_contract"),
                ("概要_当社", "our_overall_summary"),
                ("概要_相手", "their_overall_summary"),
            ]
            for label, key in items:
                before_val = (diff_before.get(key, "") or "").strip()
                after_val = (diff_after.get(key, "") or "").strip()
                if before_val == after_val:
                    continue
                st.markdown(f"- {label}")
                diff_lines = difflib.unified_diff(
                    before_val.splitlines(),
                    after_val.splitlines(),
                    fromfile="before",
                    tofile="after",
                    lineterm="",
                )
                st.code("\n".join(diff_lines), language="diff")
