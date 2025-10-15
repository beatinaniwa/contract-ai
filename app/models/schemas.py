from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Literal, List
from datetime import date

class ContractForm(BaseModel):
    # 基本
    request_date: Optional[date] = Field(None, title="依頼日")
    # 通常納期（従来: 希望納期）
    normal_due_date: Optional[date] = Field(None, title="通常納期")
    requester_department: Optional[str] = Field(None, title="依頼者_所属")
    requester_manager: Optional[str] = Field(None, title="依頼者_責任者")
    requester_staff: Optional[str] = Field(None, title="依頼者_担当者")

    # 案件
    project_type: Optional[str] = Field(None, title="案件_種別")
    project_domestic_foreign: Optional[str] = Field(None, title="案件_国内外")
    project_name: Optional[str] = Field(None, title="案件_案件名")
    activity_purpose: Optional[str] = Field(None, title="案件_活動目的")
    activity_start: Optional[str] = Field(None, title="案件_実活動時期")  # 文字列/日付混在に対応

    # 案件_契約対象品目（従来: target_item_name / deliverables を統合）
    project_target_item: Optional[str] = Field(None, title="案件_契約対象品目")

    counterparty_name: Optional[str] = Field(None, title="契約相手_名称")
    counterparty_address: Optional[str] = Field(None, title="契約相手_所在地")
    counterparty_profile: Optional[str] = Field(None, title="契約相手_プロフィール")
    counterparty_type: Optional[Literal["民間", "大学", "先生（個人）", "国等・独立行政法人等", "その他"]] = Field(None, title="概要_相手区分")
    # 概要_相手区分が 大学/先生（個人）/国等・独立行政法人等 の場合のみ表示・入力
    solution_planning_office_consultation: Optional[Literal["未", "済"]] = Field(
        None, title="ソリューション技術企画室への相談有無"
    )

    contract_form: Optional[Literal["当社書式", "相手書式"]] = Field(None, title="概要_契約書式")
    # 概要_関連契約（選択式）
    related_contract_flag: Optional[Literal["該当なし", "該当あり"]] = Field(None, title="概要_関連契約")

    # 従来の自由記述系（必要なら内部利用）
    contract_category: Optional[str] = Field(None, title="契約種別")
    procedure: Optional[str] = Field(None, title="手続")
    cost_burden: Optional[str] = Field(None, title="費用負担")
    restrictions: Optional[str] = Field(None, title="実施制限")
    notes: Optional[str] = Field(None, title="補足事項")

    amount_jpy: Optional[int] = Field(None, title="概要_金額")

    # 概要_当社/相手 の概要（統合版）
    our_overall_summary: Optional[str] = Field(None, title="概要_当社の契約活動概要および成果事業化概要")
    their_overall_summary: Optional[str] = Field(None, title="概要_相手の契約活動概要および成果事業化概要")

    # 開示される情報（複数選択 + その他自由記述）
    info_from_us: List[str] = Field(default_factory=list, title="概要_開示される情報_当社から")
    info_from_us_other: Optional[str] = Field(None, title="概要_開示される情報_当社から_その他")
    info_from_them: List[str] = Field(default_factory=list, title="概要_開示される情報_相手から")
    info_from_them_other: Optional[str] = Field(None, title="概要_開示される情報_相手から_その他")

    # どんな契約にしたいか
    desired_contract: Optional[str] = Field(None, title="どんな契約にしたいか")

    # 参考: 旧フィールド（互換のため残置）
    desired_due_date: Optional[date] = Field(None, title="希望納期（旧）")
    target_item_name: Optional[str] = Field(None, title="契約対象品目 名称（旧）")
    deliverables: Optional[str] = Field(None, title="引渡物（旧）")
    our_activity_summary: Optional[str] = Field(None, title="当社の契約活動概要（旧）")
    our_productization_summary: Optional[str] = Field(None, title="当社の成果事業化概要（旧）")
    their_activity_summary: Optional[str] = Field(None, title="相手の契約活動概要（旧）")
    their_productization_summary: Optional[str] = Field(None, title="相手の成果事業化概要（旧）")
    received_date: Optional[date] = Field(None, title="受付日（旧）")
    case_number: Optional[str] = Field(None, title="案件番号（旧）")

    # 監査メタ
    source_text: Optional[str] = None
