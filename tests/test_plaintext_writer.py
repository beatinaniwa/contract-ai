import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.plaintext_writer import format_form_as_text  # noqa: E402


def _sample_form() -> dict[str, str]:
    return {
        "affiliation": "事業開発部 スマートサービス担当",
        "target_product": "データ連携プラットフォームX",
        "activity_background": "市場からの要望が増えたため早期に販路を開拓したい。",
        "counterparty_relationship": "既存の販売代理店とNDA締結済み。追加契約の検討中。",
        "activity_details": "共同ウェビナーと営業同行を計画し、商談創出を図る。",
    }


def test_format_form_as_text_produces_expected_layout():
    expected_text = (
        "【所属(部署名まで)】\n"
        "事業開発部 スマートサービス担当\n"
        "\n"
        "【対象商材】\n"
        "データ連携プラットフォームX\n"
        "\n"
        "【活動背景・目的】\n"
        "市場からの要望が増えたため早期に販路を開拓したい。\n"
        "\n"
        "【相手方との関係・既締結の関連契約など】\n"
        "既存の販売代理店とNDA締結済み。追加契約の検討中。\n"
        "\n"
        "【活動内容】\n"
        "共同ウェビナーと営業同行を計画し、商談創出を図る。\n"
    )

    assert format_form_as_text(_sample_form()) == expected_text
