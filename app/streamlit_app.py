import hashlib
import os
from datetime import date as _dt_date

import streamlit as st
import yaml

from models.schemas import ContractForm
from services.audit import save_audit_log
from services.csv_writer import write_csv
from services.extractor import extract_contract_form
from services.text_loader import load_text_from_bytes
from services.validator import validate_form

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

    st.divider()
    st.caption("サンプルを読み込む")
    if st.button("サンプル読込", use_container_width=True):
        p = os.path.join(BASE_DIR, "sample_data", "example_input.txt")
        with open(p, "r", encoding="utf-8") as f_text:
            st.session_state["source_text"] = f_text.read()
            st.session_state["source_text_widget"] = st.session_state["source_text"]
            st.session_state["uploaded_file_digest"] = None
            sample_result = extract_contract_form(st.session_state["source_text"])
            st.session_state["extracted"] = sample_result
            if sample_result.get("error"):
                st.session_state["extract_feedback"] = ("warning", sample_result["error"])
            else:
                st.session_state["extract_feedback"] = (
                    "success",
                    "サンプルテキストから抽出しました。",
                )

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

col_form, col_preview = st.columns([3, 2])

with col_form:
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
        requester_staff = st.text_input(
            "依頼者_担当者", value=form_data.get("requester_staff", "")
        )

        # 案件_種別（最初に追加）
        project_type_options = vocab.get("project_type", [])
        default_project_type = form_data.get("project_type")
        project_type_index = (
            project_type_options.index(default_project_type)
            if default_project_type in project_type_options
            else 0
        ) if project_type_options else 0
        project_type = st.selectbox(
            "案件_種別", options=project_type_options or ["NDA"], index=project_type_index
        )

        # 案件_国内外（2番目）
        project_domestic_foreign_options = vocab.get("project_domestic_foreign", [])
        default_pdf = form_data.get("project_domestic_foreign")
        pdf_index = (
            project_domestic_foreign_options.index(default_pdf)
            if default_pdf in project_domestic_foreign_options
            else 0
        ) if project_domestic_foreign_options else 0
        project_domestic_foreign = st.selectbox(
            "案件_国内外",
            options=project_domestic_foreign_options or ["国内"],
            index=pdf_index,
        )

        project_name = st.text_input("案件_案件名", value=form_data.get("project_name", ""))
        activity_purpose = st.text_area(
            "案件_活動目的", value=form_data.get("activity_purpose", ""), height=80
        )
        activity_start = st.text_input(
            "案件_実活動時期", value=form_data.get("activity_start", "")
        )

        project_target_item = st.text_input(
            "案件_契約対象品目",
            value=form_data.get("project_target_item")
            or form_data.get("target_item_name", ""),
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

        contract_form = st.selectbox(
            "概要_契約書式", options=vocab["contract_form"], index=0
        )
        related_contract_flag = st.selectbox(
            "概要_関連契約", options=vocab.get("related_contract_flag", ["該当なし", "該当あり"]), index=0
        )

        amount_jpy = st.number_input(
            "概要_金額", min_value=0, step=1000, value=int(form_data.get("amount_jpy", 0))
        )

        # 開示される情報
        info_options = vocab.get(
            "disclosed_info_options",
            ["要求仕様", "関連技術情報", "図面", "サンプル"],
        )
        info_from_us = st.multiselect(
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

        info_from_them = st.multiselect(
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

        desired_contract = st.text_area(
            "どんな契約にしたいか", value=form_data.get("desired_contract", ""), height=80
        )

        submitted = st.form_submit_button("CSV出力", type="primary")

    if submitted:
        # 旧 related_contracts 文字列からのフォールバック: 非空なら該当あり
        related_contract_flag = related_contract_flag or (
            "該当あり" if form_data.get("related_contracts") else "該当なし"
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
            related_contract_flag=related_contract_flag or None,
            amount_jpy=amount_jpy or None,
            info_from_us=info_from_us,
            info_from_us_other=info_from_us_other,
            info_from_them=info_from_them,
            info_from_them_other=info_from_them_other,
            our_overall_summary=our_overall_summary or None,
            their_overall_summary=their_overall_summary or None,
            desired_contract=desired_contract or None,
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

with col_preview:
    st.subheader("プレビュー（抽出結果 JSON）")
    st.json(st.session_state.get("extracted", {"form": {}, "missing_fields": []}), expanded=False)

    st.subheader("CSVマッピング")
    st.write("マッピング: ", os.path.relpath(MAPPING))
