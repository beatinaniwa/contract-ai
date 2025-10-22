from __future__ import annotations

from typing import Any, Dict, Tuple


_FIELD_LAYOUT: Tuple[Tuple[str, str], ...] = (
    ("affiliation", "所属(部署名まで)"),
    ("target_product", "対象商材"),
    ("activity_background", "活動背景・目的"),
    ("counterparty_relationship", "相手方との関係・既締結の関連契約など"),
    ("activity_details", "活動内容"),
)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def format_form_as_text(form_data: Dict[str, Any]) -> str:
    """Render form data into the predefined plaintext layout."""
    lines: list[str] = []
    for field, label in _FIELD_LAYOUT:
        lines.append(f"【{label}】")
        value = _stringify(form_data.get(field))
        lines.append(value)
        lines.append("")
    text = "\n".join(lines).rstrip()
    return f"{text}\n"
