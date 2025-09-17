import os
import json
import streamlit as st
from datetime import date as _dt_date
from models.schemas import ContractForm
from services.extractor import extract_contract_form
from services.validator import validate_form
from services.excel_writer import fill_excel_template
from services.audit import save_audit_log
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING = os.path.join(BASE_DIR, "mappings", "excel_mapping.yaml")
TEMPLATE = os.path.join(BASE_DIR, "templates", "request_form_template.xlsx")

st.set_page_config(page_title="契約書作成アシスタント（MVP）", layout="wide")
st.title("契約書作成アシスタント（Excel出力 / MVP）")

with st.sidebar:
    st.header("会話入力")
    src_text = st.text_area("案件の概要や条件を自由に入力してください。", height=260)
    if st.button("抽出する", type="primary", use_container_width=True):
        result = extract_contract_form(src_text)
        st.session_state["extracted"] = result
        st.session_state["source_text"] = src_text

    st.divider()
    st.caption("サンプルを読み込む")
    if st.button("サンプル読込", use_container_width=True):
        p = os.path.join(BASE_DIR, "sample_data", "example_input.txt")
        with open(p, "r", encoding="utf-8") as f:
            st.session_state["source_text"] = f.read()
            st.session_state["extracted"] = extract_contract_form(st.session_state["source_text"])

def load_vocab():
    p = os.path.join(BASE_DIR, "policies", "vocab.yaml")
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

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
        request_date = st.date_input("依頼日", value=form_data.get("request_date") or _dt_date.today())
        desired_due_date = st.date_input("希望納期", value=form_data.get("desired_due_date") or _dt_date.today())
        requester_department = st.text_input("所属", value=form_data.get("requester_department", ""))
        requester_manager = st.text_input("責任者", value=form_data.get("requester_manager", ""))
        requester_staff = st.text_input("担当者", value=form_data.get("requester_staff", ""))

        project_name = st.text_input("案件名", value=form_data.get("project_name", ""))
        activity_purpose = st.text_area("活動目的", value=form_data.get("activity_purpose", ""), height=80)
        activity_start = st.text_input("実活動開始時期", value=form_data.get("activity_start", ""))

        target_item_name = st.text_input("契約対象品目 名称", value=form_data.get("target_item_name", ""))
        deliverables = st.text_input("引渡物", value=form_data.get("deliverables", ""))

        counterparty_name = st.text_input("相手先名称", value=form_data.get("counterparty_name", ""))
        counterparty_address = st.text_input("所在地", value=form_data.get("counterparty_address", ""))
        counterparty_type = st.selectbox("相手区分", options=vocab["counterparty_type"], index=0)

        contract_form = st.selectbox("契約書式", options=vocab["contract_form"], index=0)
        related_contracts = st.text_input("関連契約", value=form_data.get("related_contracts", ""))
        contract_category = st.text_input("契約種別", value=form_data.get("contract_category", ""))
        procedure = st.text_input("手続", value=form_data.get("procedure", ""))
        cost_burden = st.text_input("費用負担", value=form_data.get("cost_burden", ""))
        restrictions = st.text_input("実施制限", value=form_data.get("restrictions", ""))
        notes = st.text_area("補足事項", value=form_data.get("notes", ""), height=60)

        amount_jpy = st.number_input("金額（円）", min_value=0, step=1000, value=int(form_data.get("amount_jpy", 0)))

        our_activity_summary = st.text_area("当社の契約活動概要", value=form_data.get("our_activity_summary", ""), height=80)
        our_productization_summary = st.text_area("当社の成果事業化概要", value=form_data.get("our_productization_summary", ""), height=80)
        their_activity_summary = st.text_area("相手の契約活動概要", value=form_data.get("their_activity_summary", ""), height=80)
        their_productization_summary = st.text_area("相手の成果事業化概要", value=form_data.get("their_productization_summary", ""), height=80)

        received_date = st.date_input("受付日", value=form_data.get("received_date") or _dt_date.today())
        case_number = st.text_input("案件番号", value=form_data.get("case_number", ""))

        submitted = st.form_submit_button("Excel生成", type="primary")

    if submitted:
        cf = ContractForm(
            request_date=request_date or None,
            desired_due_date=desired_due_date or None,
            requester_department=requester_department or None,
            requester_manager=requester_manager or None,
            requester_staff=requester_staff or None,
            project_name=project_name or None,
            activity_purpose=activity_purpose or None,
            activity_start=activity_start or None,
            target_item_name=target_item_name or None,
            deliverables=deliverables or None,
            counterparty_name=counterparty_name or None,
            counterparty_address=counterparty_address or None,
            counterparty_type=counterparty_type or None,
            contract_form=contract_form or None,
            related_contracts=related_contracts or None,
            contract_category=contract_category or None,
            procedure=procedure or None,
            cost_burden=cost_burden or None,
            restrictions=restrictions or None,
            notes=notes or None,
            amount_jpy=amount_jpy or None,
            our_activity_summary=our_activity_summary or None,
            our_productization_summary=our_productization_summary or None,
            their_activity_summary=their_activity_summary or None,
            their_productization_summary=their_productization_summary or None,
            received_date=received_date or None,
            case_number=case_number or None,
            source_text=st.session_state.get("source_text", ""),
        )
        ok, missing = validate_form(cf)
        if not ok:
            st.error(f"必須項目が未入力です: {', '.join(missing)}")
        else:
            out_path = fill_excel_template(cf.model_dump(), MAPPING, TEMPLATE, out_dir=os.path.join(os.getcwd(), "outputs"))
            st.success("Excelを生成しました。")
            with open(out_path, "rb") as f:
                st.download_button("Excelをダウンロード", data=f, file_name=os.path.basename(out_path), mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            # 監査ログ
            audit_path = save_audit_log(cf.model_dump(), st.session_state.get("source_text", ""), out_path, out_dir=os.path.join(os.getcwd(), "outputs"))
            st.caption(f"監査ログを保存: {os.path.basename(audit_path)}")

with col_preview:
    st.subheader("プレビュー（抽出結果 JSON）")
    st.json(st.session_state.get("extracted", {"form": {}, "missing_fields": []}), expanded=False)

    st.subheader("テンプレ & マッピング")
    st.write("テンプレート: ", os.path.relpath(TEMPLATE))
    st.write("マッピング: ", os.path.relpath(MAPPING))
