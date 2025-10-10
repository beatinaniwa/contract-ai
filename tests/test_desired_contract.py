import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.desired_contract import summarize_desired_contract


def test_summarize_desired_contract_extracts_facts_and_questions():
    text = (
        "本件では当社の特許出願とノウハウの権利化を目指す。"
        "相手には研究段階のデータを開示。"
        "量産製品については当社製品のみ実施し、相手や顧客へのライセンスは予定しない。"
        "第三者特許の抵触リスクがあるため、FTOを確認中。"
    )

    summary, questions = summarize_desired_contract(text)

    assert "1. 財活動上の目論見" in summary
    assert "特許出願" in summary
    assert "権利化" in summary
    assert "3. 上記2." in summary
    assert "当社製品のみ実施" in summary
    assert "ライセンスは予定しない" in summary
    assert "4. 上記1." in summary
    assert "FTO" in summary or "抵触" in summary

    # Some viewpoints may be missing; ensure we ask up to 3 concise questions
    assert 0 <= len(questions) <= 3


def test_summarize_desired_contract_questions_when_empty():
    empty = "案件の背景のみ記載。具体的な方針や範囲、リスクの記載はなし。"
    summary, questions = summarize_desired_contract(empty)
    # All sections should exist with 記載なし markers somewhere
    assert "1. 財活動上の目論見" in summary
    assert "2. 財活動上の目論見" in summary
    assert "3. 上記2." in summary
    assert "4. 上記1." in summary
    assert 1 <= len(questions) <= 3

