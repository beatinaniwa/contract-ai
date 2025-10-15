import sys
from datetime import date
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import config_loader  # noqa: E402
from services import extractor  # noqa: E402


def _clear_gemini_state(monkeypatch) -> None:
    extractor._get_client.cache_clear()
    config_loader.load_secrets.cache_clear()
    monkeypatch.delenv("STREAMLIT_SECRETS_PATH", raising=False)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_extract_contract_form_without_api_key(monkeypatch, tmp_path):
    _clear_gemini_state(monkeypatch)
    missing_config = tmp_path / "missing.toml"
    monkeypatch.setenv("STREAMLIT_SECRETS_PATH", str(missing_config))
    config_loader.load_secrets.cache_clear()
    extractor._get_client.cache_clear()

    sample = "案件名: テスト案件\n相手先: テスト株式会社\n金額: 120万円\n"
    result = extractor.extract_contract_form(sample)

    assert result["form"]["project_name"] == "テスト案件"
    assert result["form"]["counterparty_name"] == "テスト株式会社"
    assert result["form"]["amount_jpy"] == 1_200_000
    assert result["missing_fields"] == []
    assert "error" in result


def test_extract_contract_form_uses_gemini_payload(monkeypatch, tmp_path):
    _clear_gemini_state(monkeypatch)
    config_path = tmp_path / "secrets.toml"
    config_path.write_text("gemini_api_key = \"test-key\"\n", encoding="utf-8")
    monkeypatch.setenv("STREAMLIT_SECRETS_PATH", str(config_path))
    config_loader.load_secrets.cache_clear()
    extractor._get_client.cache_clear()

    fake_payload = {
        "form": {
            "project_name": "Gemini案件",
            "counterparty_name": "合同会社サンプル",
            "amount_jpy": 3_500_000,
            "request_date": "2024-03-01",
            "counterparty_type": "民間",
        }
    }

    monkeypatch.setattr(extractor, "_call_gemini", lambda _: fake_payload)

    result = extractor.extract_contract_form("入力テキスト")

    assert "error" not in result
    assert result["form"]["project_name"] == "Gemini案件"
    assert result["form"]["counterparty_name"] == "合同会社サンプル"
    assert result["form"]["amount_jpy"] == 3_500_000
    assert result["form"]["request_date"] == date(2024, 3, 1)
    assert result["missing_fields"] == []
