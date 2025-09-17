import re
from datetime import datetime
from typing import Dict, Any
from dateutil import parser
from .normalizer import normalize_amount_jpy

def try_parse_date(text: str):
    # Try a few date formats (YYYY/MM/DD, YYYY年M月D日, YYYY-M-D, etc.)
    candidates = re.findall(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日)', text)
    if candidates:
        for c in candidates:
            try:
                return parser.parse(c).date()
            except Exception:
                continue
    return None

def extract_contract_form(text: str) -> Dict[str, Any]:
    """
    非LLMの簡易抽出（正規表現ベース）
    実運用では LLM + スキーマバリデーションに置き換えてください。
    """
    data: Dict[str, Any] = {}
    t = text

    # 金額（～万円/～円）
    m = re.search(r'(\d{1,3}(?:,\d{3})*|\d+)\s*万円', t)
    if m:
        data["amount_jpy"] = normalize_amount_jpy(m.group(1) + "万円")
    else:
        m2 = re.search(r'(\d{1,3}(?:,\d{3})*|\d+)\s*円', t)
        if m2:
            data["amount_jpy"] = normalize_amount_jpy(m2.group(1) + "円")

    # 案件名
    m = re.search(r'(案件名|テーマ)[:：]?\s*([^\n]+)', t)
    if m:
        data["project_name"] = m.group(2).strip()

    # 相手先
    m = re.search(r'(相手先|取引先|カウンターパーティ|会社名)[:：]?\s*([^\n]+)', t)
    if m:
        data["counterparty_name"] = m.group(2).strip()

    # 住所
    m = re.search(r'(所在地|住所)[:：]?\s*([^\n]+)', t)
    if m:
        data["counterparty_address"] = m.group(2).strip()

    # 契約書式
    if "当社書式" in t:
        data["contract_form"] = "当社書式"
    if "相手書式" in t or "相手先書式" in t:
        data["contract_form"] = "相手書式"

    # 相手区分（キーワード推定）
    if "大学" in t:
        data["counterparty_type"] = "大学"
    elif "独立行政法人" in t or "国立" in t or "省庁" in t:
        data["counterparty_type"] = "国等・独立行政法人等"
    elif "先生" in t or "個人" in t:
        data["counterparty_type"] = "先生（個人）"
    else:
        data.setdefault("counterparty_type", "民間")

    # 日付（依頼日/受付日/希望納期のいずれかに推定で入れる）
    d = try_parse_date(t)
    if d:
        data["request_date"] = d

    # 概要系（ざっくり）
    m = re.search(r'(目的|活動目的)[:：]?\s*([^\n]+)', t)
    if m:
        data["activity_purpose"] = m.group(2).strip()

    m = re.search(r'(開始|開始時期|実施時期)[:：]?\s*([^\n]+)', t)
    if m:
        data["activity_start"] = m.group(2).strip()

    # 引渡物/成果物
    m = re.search(r'(引渡物|成果物)[:：]?\s*([^\n]+)', t)
    if m:
        data["deliverables"] = m.group(2).strip()

    # 案件番号
    m = re.search(r'案件番号[:：]?\s*([A-Za-z0-9\-\[\]]+)', t)
    if m:
        data["case_number"] = m.group(1).strip()

    return {
        "form": data,
        "missing_fields": []  # Streamlit側で pydantic モデルと語彙で不足項目をチェック
    }
