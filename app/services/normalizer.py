import re

def normalize_amount_jpy(text: str) -> int:
    """
    '350万円' -> 3500000, '3,500,000円' -> 3500000
    """
    t = text.replace(',', '')
    m_man = re.search(r'(\d+)\s*万\s*円?', t)
    if m_man:
        return int(m_man.group(1)) * 10000
    m_en = re.search(r'(\d+)\s*円', t)
    if m_en:
        return int(m_en.group(1))
    # fallback: plain digits
    m_plain = re.search(r'(\d+)', t)
    if m_plain:
        return int(m_plain.group(1))
    return 0
