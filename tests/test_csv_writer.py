import os
import sys
from datetime import date
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.csv_writer import write_csv


def test_write_csv_creates_file(tmp_path):
    mapping = os.path.join("app", "mappings", "csv_mapping.yaml")

    form = {
        "request_date": date(2024, 9, 1),
        "normal_due_date": date(2024, 9, 30),
        "requester_department": "研究開発部",
        "requester_manager": "山田",
        "requester_staff": "佐藤",
        "project_name": "自動化装置の開発",
        "activity_purpose": "搬送自動化の試作",
        "activity_start": "2024年10月",
        "project_target_item": "装置A",
        "counterparty_name": "ニチエツ株式会社",
        "counterparty_address": "神奈川県横浜市",
        "counterparty_profile": "半導体加工装置メーカー。主要顧客はX社。",
        "counterparty_type": "民間",
        "contract_form": "当社書式",
        "related_contract_flag": "該当なし",
        "amount_jpy": 2500000,
        "info_from_us": ["要求仕様", "図面"],
        "info_from_them": ["サンプル", "その他"],
        "info_from_them_other": "試験片Aを想定",
        "our_overall_summary": "試作機設計/試験/結果整理",
        "their_overall_summary": "評価/フィードバック/量産検討",
        "desired_contract": "秘密保持と成果物の権利帰属を当社とする",
    }

    out_path = write_csv(form, mapping_yaml_path=mapping, out_dir=tmp_path.as_posix())
    assert out_path.endswith(".csv")
    assert os.path.exists(out_path)

    with open(out_path, "rb") as f:
        content = f.read()
    # Starts with UTF-8 BOM
    assert content.startswith(b"\xef\xbb\xbf")

    text = content.decode("utf-8-sig")
    # Single header row + single data row
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 2
