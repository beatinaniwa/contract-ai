from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


class ContractForm(BaseModel):
    affiliation: Optional[str] = Field(None, title="所属(部署名まで)")
    target_product: Optional[str] = Field(None, title="対象商材")
    activity_background: Optional[str] = Field(None, title="活動背景・目的")
    counterparty_relationship: Optional[str] = Field(
        None, title="相手方との関係・既締結の関連契約など"
    )
    activity_details: Optional[str] = Field(None, title="活動内容")

    # 監査メタ
    source_text: Optional[str] = None
