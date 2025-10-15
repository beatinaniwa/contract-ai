import hashlib
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
from services.text_loader import load_text_from_bytes
from services.validator import validate_form
from services.desired_contract import summarize_desired_contract

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING = os.path.join(BASE_DIR, "mappings", "csv_mapping.yaml")

st.set_page_config(page_title="契約書作成アシスタント（MVP）", layout="wide")
st.title("契約書作成アシスタント（CSV出力 / MVP）")

if "source_text_widget" not in st.session_state:
    st.session_state["source_text_widget"] = st.session_state.get("source_text", "")

st.session_state.setdefault("uploaded_file_digest", None)

with st.sidebar:
    st.header("会話入力")
    uploaded_file = st.file_uploader(
        "案件の概要や条件のファイルをアップロード",
        type=["pdf", "txt"],
        accept_multiple_files=False,
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
    )
    if st.button("抽出する", type="primary", use_container_width=True):
        result = extract_contract_form(src_text)
        st.session_state["extracted"] = result
        st.session_state["source_text"] = src_text
        if result.get("error"):
            st.session_state["extract_feedback"] = ("warning", result["error"])
        else:
            st.session_state["extract_feedback"] = ("success", "Geminiで抽出結果を取得しました。")


feedback = st.session_state.pop("extract_feedback", None)
if feedback:
    status, message = feedback
    if status == "success":
        st.success(message)
    elif status == "error":
        st.error(message)
    else:
        st.warning(message)


def load_vocab():
    p = os.path.join(BASE_DIR, "policies", "vocab.yaml")
    with open(p, "r", encoding="utf-8") as f_yaml:
        return yaml.safe_load(f_yaml)


vocab = load_vocab()

col_main = st.container()

with col_main:
    st.subheader("フォーム（編集可）")

    # 既存データの展開
    extracted = st.session_state.get("extracted", {"form": {}, "missing_fields": []})
    form_data = extracted.get("form", {})

    # 動的フォーム
    with st.form("contract_form"):
        # 基本情報
        request_date = st.date_input(
            "依頼日", value=form_data.get("request_date") or _dt_date.today()
        )
        normal_due_date = st.date_input(
            "通常納期",
            value=form_data.get("normal_due_date")
            or form_data.get("desired_due_date")
            or _dt_date.today(),
        )
        requester_department = st.text_input(
            "依頼者_所属", value=form_data.get("requester_department", "")
        )
        requester_manager = st.text_input(
            "依頼者_責任者", value=form_data.get("requester_manager", "")
        )
        requester_staff = st.text_input("依頼者_担当者", value=form_data.get("requester_staff", ""))

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
            "案件_種別", options=project_type_options or ["NDA"], index=project_type_index
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
        )

        project_name = st.text_input("案件_案件名", value=form_data.get("project_name", ""))
        activity_purpose = st.text_area(
            "案件_活動目的", value=form_data.get("activity_purpose", ""), height=80
        )
        activity_start = st.text_input("案件_実活動時期", value=form_data.get("activity_start", ""))

        # 契約対象品目（単一選択）
        project_target_item_options = vocab.get(
            "project_target_item", ["ハード", "ソフト", "技術", "役務", "その他"]
        )
        default_target_raw = form_data.get("project_target_item") or form_data.get(
            "target_item_name"
        )
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
        )

        counterparty_name = st.text_input(
            "契約相手_名称", value=form_data.get("counterparty_name", "")
        )
        counterparty_address = st.text_input(
            "契約相手_所在地", value=form_data.get("counterparty_address", "")
        )
        counterparty_profile = st.text_area(
            "契約相手_プロフィール", value=form_data.get("counterparty_profile", ""), height=80
        )
        counterparty_type = st.selectbox(
            "概要_相手区分", options=vocab["counterparty_type"], index=0
        )

        contract_form = st.selectbox("概要_契約書式", options=vocab["contract_form"], index=0)
        related_contract_flag = st.selectbox(
            "概要_関連契約",
            options=vocab.get("related_contract_flag", ["該当なし", "該当あり"]),
            index=0,
        )

        amount_jpy = st.number_input(
            "概要_金額", min_value=0, step=1000, value=int(form_data.get("amount_jpy", 0))
        )

        # 開示される情報
        info_options = vocab.get(
            "disclosed_info_options",
            ["要求仕様", "関連技術情報", "図面", "サンプル"],
        )
        info_from_us: List[str] = st.multiselect(
            "概要_開示される情報_当社から",
            options=info_options,
            default=form_data.get("info_from_us", []),
        )
        info_from_us_other = st.text_input(
            "概要_開示される情報_当社から_その他",
            value=form_data.get("info_from_us_other", ""),
            placeholder="他に開示予定があれば記入（空でも可）",
            help="選択肢にない開示事項があれば1行で記入。未入力可。",
            key="info_from_us_other",
        )

        info_from_them: List[str] = st.multiselect(
            "概要_開示される情報_相手から",
            options=info_options,
            default=form_data.get("info_from_them", []),
        )
        info_from_them_other = st.text_input(
            "概要_開示される情報_相手から_その他",
            value=form_data.get("info_from_them_other", ""),
            placeholder="他に相手からの開示があれば記入（空でも可）",
            help="選択肢にない相手からの開示事項があれば1行で記入。未入力可。",
            key="info_from_them_other",
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
        our_overall_summary = st.text_area(
            "概要_当社の契約活動概要および成果事業化概要",
            value=our_overall_summary_default or "",
            height=100,
        )

        their_overall_summary_default = form_data.get("their_overall_summary")
        if not their_overall_summary_default:
            parts = [
                form_data.get("their_activity_summary", "").strip(),
                form_data.get("their_productization_summary", "").strip(),
            ]
            parts = [p for p in parts if p]
            their_overall_summary_default = "\n".join(parts)
        their_overall_summary = st.text_area(
            "概要_相手の契約活動概要および成果事業化概要",
            value=their_overall_summary_default or "",
            height=100,
        )

        # 「どんな契約にしたいか」のガイダンス（テキストエリアの外に説明を表示）
        st.markdown(
            """
            どんな契約にしたいか（記入ガイド）

            1. 財活動上の目論見（知財創出/権利化/ライセンス/知財売買/知財保証/・・・）
            2. 財活動上の目論見（知財創出/権利化/ライセンス/知財売買/知財保証/・・・）
            3. 上記2. に関する事業上の実施や許諾の内容（当社製品が実施品/当社と取引後の相手や顧客の製品が実施品/取引の前後に関係なく双方の製品が実施品/・・・）
            4. 上記1. および2. から生じ得る上記3. や知財上のリスク（自己実施上の支障/第三者による実施/コンタミによる出願上の支障/第三者からの権利行使/実施料の発生/・・・）
            """
        )

        # 初期テンプレート（未入力時は番号のみ）
        def _strip_desired_titles(text: str) -> str:
            """UI表示用に、長い説明タイトルを番号だけに置換する。

            例: "1. 財活動上の目論見（…）" -> "1. "
            箇条書き ("- …") や番号行に直接書かれた本文 ("1. 本文") は残す。
            生成側のバリエーションに対応するため、タイトル文はパターンで判定。
            """
            if not text:
                return text
            title_patterns = [
                re.compile(r"^財活動上の目論見（.*）$"),
                re.compile(r"^上記2\.\s*に関する事業上の実施や許諾の内容（.*）$"),
                re.compile(r"^上記1\.\s*および2\.\s*から生じ得る上記3\.\s*や知財上のリスク（.*）$"),
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

        desired_contract_default = (form_data.get("desired_contract", "") or "").strip()
        if desired_contract_default:
            desired_contract_default = _strip_desired_titles(desired_contract_default)
        else:
            desired_contract_default = "\n".join(["1. ", "", "2. ", "", "3. ", "", "4. "]) + "\n"

        desired_contract = st.text_area(
            "どんな契約にしたいか",
            value=desired_contract_default,
            height=300,
            help="番号に続けて内容を記入。必要に応じて各番号の下に '- ' で箇条書きも可。",
        )

        submitted = st.form_submit_button("CSV出力", type="primary")

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
            st.error(f"必須項目が未入力です: {', '.join(missing)}")
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
        st.subheader("追加で確認したい点 (最大3件)")
        answers: Dict[int, str] = {}
        for idx, q in enumerate(follow_up):
            st.markdown(f"Q{idx + 1}. {q}")
            ans_key = f"qa_answer_{idx}"
            answers[idx] = st.text_area(
                label=f"回答{idx + 1}",
                key=ans_key,
                height=60,
                placeholder="（任意）必要十分な記載にするための補足を記入。未入力でも可。",
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
                2: "2. 財活動上の目論見（知財創出/権利化/ライセンス/知財売買/知財保証/・・・）",
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

        if st.button("回答を送信", type="secondary", use_container_width=True):
            form_data = extracted_payload.get("form", {})
            source_text = st.session_state.get("source_text", "")
            base_dc = (
                form_data.get("desired_contract") or summarize_desired_contract(source_text)[0]
            )

            our_summary = form_data.get("our_overall_summary", "") or ""
            their_summary = form_data.get("their_overall_summary", "") or ""

            remaining_questions: List[str] = []
            answered_qas: List[Dict[str, str]] = []
            for idx, q in enumerate(follow_up):
                ans = (answers.get(idx) or "").strip()
                if not ans:
                    remaining_questions.append(q)
                    continue
                answered_qas.append({"question": q, "answer": ans})

            updated_dc = base_dc
            explanation_for_ui: Dict[str, Dict[str, str]] | None = None
            try:
                if answered_qas:
                    updated = update_contract_sections_with_gemini(
                        source_text=source_text,
                        current_values={
                            "desired_contract": base_dc or "",
                            "our_overall_summary": our_summary or "",
                            "their_overall_summary": their_summary or "",
                        },
                        qa=answered_qas,
                    )
                    updated_dc = updated.get("desired_contract", base_dc) or base_dc
                    our_summary = updated.get("our_overall_summary", our_summary) or our_summary
                    their_summary = (
                        updated.get("their_overall_summary", their_summary) or their_summary
                    )
                    maybe_expl = updated.get("explanation")
                    if isinstance(maybe_expl, dict):
                        explanation_for_ui = maybe_expl  # type: ignore[assignment]
            except Exception:
                sections = _parse_sections(base_dc)
                for qa in answered_qas:
                    q = qa["question"]
                    ans = qa["answer"]
                    sec = _map_question_to_section(q)
                    if sec:
                        sections.setdefault(sec, [])
                        if ans not in sections[sec]:
                            sections[sec].append(ans)
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
                        else "回答が空または変更不要のため維持（Gemini未使用のフォールバック）",
                    },
                    "our_overall_summary": {
                        "action": "updated"
                        if form_data.get("our_overall_summary", "") != our_summary
                        else "unchanged",
                        "reason": "回答（当社/弊社を含む）を反映"
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
            st.session_state.setdefault("extracted", {"form": {}, "missing_fields": []})
            st.session_state["extracted"].setdefault("form", {})
            st.session_state["extracted"]["form"]["desired_contract"] = updated_dc
            if our_summary:
                st.session_state["extracted"]["form"]["our_overall_summary"] = our_summary
            if their_summary:
                st.session_state["extracted"]["form"]["their_overall_summary"] = their_summary

            if remaining_questions:
                st.session_state["extracted"]["follow_up_questions"] = remaining_questions
            else:
                st.session_state["extracted"].pop("follow_up_questions", None)

            st.success("回答をフォームに反映しました。左側フォームの値が更新されます。")

            if explanation_for_ui is not None:
                st.session_state["qa_update_explanation"] = explanation_for_ui
                st.session_state["qa_update_engine"] = "gemini"
            else:
                st.session_state["qa_update_explanation"] = st.session_state.get(
                    "qa_update_explanation", {}
                )
                st.session_state["qa_update_engine"] = "fallback"

    expl = st.session_state.get("qa_update_explanation")
    if expl:
        engine = st.session_state.get("qa_update_engine", "gemini")
        st.subheader("回答反映の判断結果")
        if engine == "gemini":
            st.caption("Gemini 2.5 Pro による更新判断")
        else:
            st.caption("Gemini未使用のフォールバックによる更新判断")

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
