from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date

class ContractForm(BaseModel):
    # 基本
    request_date: Optional[date] = Field(None, title="依頼日")
    desired_due_date: Optional[date] = Field(None, title="希望納期")
    requester_department: Optional[str] = Field(None, title="所属")
    requester_manager: Optional[str] = Field(None, title="責任者")
    requester_staff: Optional[str] = Field(None, title="担当者")

    project_name: Optional[str] = Field(None, title="案件名")
    activity_purpose: Optional[str] = Field(None, title="活動目的")
    activity_start: Optional[str] = Field(None, title="実活動開始時期")  # 文字列/日付混在に対応

    target_item_name: Optional[str] = Field(None, title="契約対象品目 名称")
    deliverables: Optional[str] = Field(None, title="引渡物")

    counterparty_name: Optional[str] = Field(None, title="相手先名称")
    counterparty_address: Optional[str] = Field(None, title="所在地")
    counterparty_type: Optional[Literal["民間", "大学", "先生（個人）", "国等・独立行政法人等", "その他"]] = Field(None, title="相手区分")

    contract_form: Optional[Literal["当社書式", "相手書式"]] = Field(None, title="契約書式")
    related_contracts: Optional[str] = Field(None, title="関連契約")
    contract_category: Optional[str] = Field(None, title="契約種別")
    procedure: Optional[str] = Field(None, title="手続")
    cost_burden: Optional[str] = Field(None, title="費用負担")
    restrictions: Optional[str] = Field(None, title="実施制限")
    notes: Optional[str] = Field(None, title="補足事項")

    amount_jpy: Optional[int] = Field(None, title="金額（円）")

    our_activity_summary: Optional[str] = Field(None, title="当社の契約活動概要")
    our_productization_summary: Optional[str] = Field(None, title="当社の成果事業化概要")
    their_activity_summary: Optional[str] = Field(None, title="相手の契約活動概要")
    their_productization_summary: Optional[str] = Field(None, title="相手の成果事業化概要")

    received_date: Optional[date] = Field(None, title="受付日")
    case_number: Optional[str] = Field(None, title="案件番号")

    # 監査メタ
    source_text: Optional[str] = None
