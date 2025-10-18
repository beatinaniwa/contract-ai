import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.csv_writer import write_csv  # noqa: E402


def test_write_csv_creates_file(tmp_path):
    mapping = os.path.join("app", "mappings", "csv_mapping.yaml")

    form = {
        "affiliation": "事業開発部 スマートサービス担当",
        "target_product": "データ連携プラットフォームX",
        "activity_background": "市場からの要望が増えたため早期に販路を開拓したい。",
        "counterparty_relationship": "既存の販売代理店とNDA締結済み。追加契約の検討中。",
        "activity_details": "共同ウェビナーと営業同行を計画し、商談創出を図る。",
    }

    out_path = write_csv(form, mapping_yaml_path=mapping, out_dir=tmp_path.as_posix())
    assert out_path.endswith(".csv")
    assert os.path.exists(out_path)

    with open(out_path, "rb") as f:
        content = f.read()
    assert content.startswith(b"\xef\xbb\xbf")

    text = content.decode("utf-8-sig")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 2
