from __future__ import annotations

import re
from typing import List, Tuple


def _split_sentences_jp(text: str) -> List[str]:
    """Lightweight sentence splitter for Japanese text.

    Splits on '。', '！', '？' and newlines, and trims whitespace.
    Returns non-empty sentences only.
    """
    if not text:
        return []
    # Normalize line breaks and split by punctuation commonly used as sentence enders
    tmp = re.sub(r"[\r\t]", " ", text)
    parts = re.split(r"[。！？\n]", tmp)
    return [p.strip() for p in parts if p and p.strip()]


def _collect_matches(sentences: List[str], keywords: List[str], limit: int = 3) -> List[str]:
    found: List[str] = []
    if not sentences or not keywords:
        return found
    pattern = re.compile("|".join(map(re.escape, keywords)))
    for s in sentences:
        if pattern.search(s):
            found.append(s)
            if len(found) >= limit:
                break
    return found


def summarize_desired_contract(text: str) -> Tuple[str, List[str]]:
    """Extract facts for the 4 viewpoints and build a structured summary.

    Never infer; only include sentences that appear in the source text.
    If a viewpoint has no extractable facts, mark as '記載なし'.
    Returns a tuple of (summary_text, follow_up_questions).
    The follow-up questions are at most 3 and phrased for easy user answers.
    """
    sentences = _split_sentences_jp(text)

    # Viewpoint keywords
    vp1_or_2_keywords = [
        "知財", "特許", "出願", "権利化", "権利帰属", "ライセンス", "実施許諾", "譲渡", "売買", "保証", "表明",
        "補償", "ノウハウ", "著作権", "商標", "秘密", "NDA", "機密保持",
    ]
    vp3_keywords = [
        "実施", "許諾", "サブライセンス", "対象", "範囲", "地域", "期間", "用途", "製品", "当社製品",
        "相手の製品", "顧客", "双方", "第三者", "量産", "販売", "提供",
    ]
    vp4_keywords = [
        "リスク", "支障", "障害", "第三者", "権利行使", "侵害", "紛争", "コンタミ", "混入", "実施料",
        "ロイヤリティ", "費用", "損害", "補償", "無効", "抵触", "FTO",
    ]

    vp1 = _collect_matches(sentences, vp1_or_2_keywords)
    # Intentionally collect independently for viewpoint 2 (spec may be duplicated label)
    vp2 = _collect_matches([s for s in sentences if s not in vp1], vp1_or_2_keywords)
    vp3 = _collect_matches(sentences, vp3_keywords)
    vp4 = _collect_matches(sentences, vp4_keywords)

    def _format_section(title: str, facts: List[str]) -> str:
        if facts:
            # Keep direct quotes to avoid inference
            return f"{title}\n- " + "\n- ".join(facts)
        return f"{title}\n- 記載なし"

    sections: List[str] = [
        _format_section(
            "1. 財活動上の目論見（知財創出/権利化/ライセンス/知財売買/知財保証/・・・）",
            vp1,
        ),
        _format_section(
            "2. 財活動上の目論見（知財創出/権利化/ライセンス/知財売買/知財保証/・・・）",
            vp2,
        ),
        _format_section(
            "3. 上記2. に関する事業上の実施や許諾の内容（当社製品が実施品/当社と取引後の相手や顧客の製品が実施品/取引の前後に関係なく双方の製品が実施品/・・・）",
            vp3,
        ),
        _format_section(
            "4. 上記1. および2. から生じ得る上記3. や知財上のリスク（自己実施上の支障/第三者による実施/コンタミによる出願上の支障/第三者からの権利行使/実施料の発生/・・・）",
            vp4,
        ),
    ]

    summary = "\n\n".join(sections)

    # Build up to 3 questions for missing areas
    questions: List[str] = []
    if not vp1 and len(questions) < 3:
        questions.append(
            "（どんな契約にしたいか補足）知財の取り扱い方針（創出/権利化/ライセンス/売買/保証）のうち、今回の目標は何ですか？"
        )
    if not vp2 and len(questions) < 3:
        questions.append(
            "（どんな契約にしたいか補足）知財面で追加で重視したい事項（例: ノウハウ帰属、譲渡可否、保証範囲）がありますか？"
        )
    if not vp3 and len(questions) < 3:
        questions.append(
            "（どんな契約にしたいか補足）実施・許諾の対象と範囲（当社製品/相手製品/双方、地域・期間、サブライセンス可否）を教えてください。"
        )
    if not vp4 and len(questions) < 3:
        questions.append(
            "（どんな契約にしたいか補足）想定リスク（自己実施の支障、第三者権利、コンタミ、実施料 等）があれば列挙してください。"
        )

    # Ensure at most 3
    questions = questions[:3]
    return summary, questions
