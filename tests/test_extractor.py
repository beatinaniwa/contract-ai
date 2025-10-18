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
        },
        "follow_up_questions": [
            "対象商材のラインアップは？",
            "所属部署名を正確に教えてください。",
            "活動内容の詳細を教えてください。",
        ],
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
    assert result["follow_up_questions"][0] == "活動内容の詳細を教えてください。"
    assert len(result["follow_up_questions"]) == 3


def test_update_form_with_followups_uses_gemini(monkeypatch):
    current = {
        "affiliation": "",
        "target_product": "AI分析サービス",
        "activity_background": "",
        "counterparty_relationship": "",
        "activity_details": "",
    }
    qa = [{"question": "所属はどちらですか？", "answer": "事業開発部 第二グループ"}]

    monkeypatch.setattr(
        extractor,
        "_call_gemini_follow_up",
        lambda source_text, form, qa_pairs: {
            "updated_form": {
                "affiliation": "事業開発部 第二グループ",
                "activity_background": "顧客の要望に応えるため",
            },
            "follow_up_questions": ["活動内容の詳細を教えてください。"],
            "explanation": {},
        },
    )

    result = extractor.update_form_with_followups("元テキスト", current, qa, current_round=1, max_rounds=2)
    assert result["form"]["affiliation"] == "事業開発部 第二グループ"
    assert result["form"]["activity_background"] == "顧客の要望に応えるため"
    assert result["follow_up_questions"] == ["活動内容の詳細を教えてください。"]
    assert result["next_round"] == 2
    assert result["max_rounds_reached"] is True


def test_update_form_with_followups_fallback(monkeypatch):
    monkeypatch.setattr(
        extractor,
        "_call_gemini_follow_up",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("boom")),
    )

    current = {
        "affiliation": "",
        "target_product": "",
        "activity_background": "",
        "counterparty_relationship": "",
        "activity_details": "",
    }
    qa = [
        {"question": "所属（部署名まで）を教えてください。", "answer": "営業本部 第一営業部"},
        {"question": "対象商材は？", "answer": "データ連携プラットフォーム"},
    ]

    result = extractor.update_form_with_followups("元テキスト", current, qa, current_round=1, max_rounds=2)
    assert result["form"]["affiliation"] == "営業本部 第一営業部"
    assert result["form"]["target_product"] == "データ連携プラットフォーム"
    assert result["follow_up_questions"] == []
    assert result["next_round"] == 2
    assert result["max_rounds_reached"] is True
