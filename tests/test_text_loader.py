import io

import pytest

from services.text_loader import load_text_from_bytes


def _make_pdf_with_text(text: str) -> bytes:
    def _escape(content: str) -> str:
        return content.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    escaped = _escape(text)
    content = f"BT\n/F1 24 Tf\n72 712 Td\n({escaped}) Tj\nET\n"
    content_bytes = content.encode("utf-8")
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content_bytes)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(f"{index} 0 obj\n".encode("ascii"))
        buffer.write(obj.encode("utf-8"))
        buffer.write(b"\nendobj\n")

    xref_pos = buffer.tell()
    buffer.write(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    buffer.write(b"trailer\n")
    buffer.write(f"<< /Size {len(offsets)} /Root 1 0 R >>\n".encode("ascii"))
    buffer.write(b"startxref\n")
    buffer.write(f"{xref_pos}\n".encode("ascii"))
    buffer.write(b"%%EOF")
    return buffer.getvalue()


def test_load_text_from_txt_bytes():
    content = "案件概要を記載したサンプルテキストです。\n詳細条件も含まれます。"
    result = load_text_from_bytes(content.encode("utf-8"), "sample.txt")
    assert "案件概要" in result
    assert "詳細条件" in result


def test_load_text_from_pdf_bytes():
    pdf_bytes = _make_pdf_with_text("Hello PDF")
    result = load_text_from_bytes(pdf_bytes, "sample.pdf")
    assert result == "Hello PDF"


def test_load_text_from_bytes_raises_for_unknown_extension():
    with pytest.raises(ValueError):
        load_text_from_bytes(b"binary", "sample.docx")


def test_load_text_from_bytes_raises_for_empty_payload():
    with pytest.raises(ValueError):
        load_text_from_bytes(b"", "empty.txt")
