import sys
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

    sample = (
        "所属：事業開発部\n"
        "対象商材: AI分析サービス\n"
        "活動背景: 顧客要望の増加への対応\n"
        "相手方との関係: 既にNDA締結済みの販売代理店\n"
        "活動内容: PoCと販売契約交渉を実施予定\n"
    )
    result = extractor.extract_contract_form(sample)

    assert result["form"]["affiliation"] == "事業開発部"
    assert result["form"]["target_product"] == "AI分析サービス"
    assert result["form"]["activity_background"] == "顧客要望の増加への対応"
    assert result["form"]["counterparty_relationship"] == "既にNDA締結済みの販売代理店"
    assert result["form"]["activity_details"] == "PoCと販売契約交渉を実施予定"
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
            "affiliation": "経営企画本部",
            "target_product": "ロボティクスプラットフォーム",
            "activity_background": "国内市場での拡販が目的",
            "counterparty_relationship": "販売代理店と既に基本契約を締結済み",
            "activity_details": "共同セミナーと営業訪問を実施予定",
        }
    }

    monkeypatch.setattr(extractor, "_call_gemini", lambda _: fake_payload)

    result = extractor.extract_contract_form("入力テキスト")

    assert "error" not in result
    assert result["form"]["affiliation"] == "経営企画本部"
    assert result["form"]["target_product"] == "ロボティクスプラットフォーム"
    assert result["form"]["activity_background"] == "国内市場での拡販が目的"
    assert result["form"]["counterparty_relationship"] == "販売代理店と既に基本契約を締結済み"
    assert result["form"]["activity_details"] == "共同セミナーと営業訪問を実施予定"
    assert result["missing_fields"] == []
