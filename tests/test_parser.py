"""Document ingestion tests (DOCX/PDF/TXT parsing)."""

from __future__ import annotations

import io

import docx

from lawrisk.parser import parse_document


def _make_docx() -> bytes:
    d = docx.Document()
    d.add_heading("Master Services Agreement", 0)
    d.add_paragraph("Paragraph one with a term of 24 months.")
    d.add_paragraph("This agreement is governed by the laws of England.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _make_pdf(text: str) -> bytes:
    """Build a minimal single-page PDF in memory (no external library).

    Enough structure for pypdf to accept: one page, a Type1 Helvetica font and
    a content stream drawing the given text on a single line.
    """
    escaped = (
        text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1")
    )
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
        b"5 0 obj << /Length 6 0 R >> stream",
        b"BT /F1 12 Tf 72 720 Td (" + escaped + b") Tj ET",
        b"endstream endobj",
        b"6 0 obj 62 endobj",
    ]
    chunks = [b"%PDF-1.4"]
    for obj in objects:
        chunks.append(obj)
    body = b"\n".join(chunks)

    # xref table over the object byte offsets (excluding the %PDF header line).
    offsets: list[int] = []
    cursor = len(b"%PDF-1.4\n")
    for obj in objects:
        offsets.append(cursor)
        cursor += len(obj) + 1
    xref = b"xref\n0 %d\n0000000000 65535 f\n" % (len(objects) + 1)
    xref += b"".join(f"{off:010d} 00000 n\n".encode() for off in offsets)

    trailer = (
        b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF"
        % (len(objects) + 1, len(body) + len(b"\n"))
    )
    return b"\n".join([b"%PDF-1.4\n" + body, xref, trailer])


def test_docx_parsing_gets_paragraphs_and_headings():
    dp = parse_document(_make_docx(), "d1", "agreement.docx")
    assert dp.document_id == "d1"
    assert any("Paragraph one" in p for p in dp.paragraphs)
    assert dp.word_count > 0


def test_docx_field_extraction():
    dp = parse_document(_make_docx(), "d2", "agreement.docx")
    laws = [f.value for f in dp.fields if f.name == "governing_law"]
    assert laws and "England" in laws[0]


def test_plain_text_parsing():
    raw = "This is the first paragraph.\n\nThis is the second.\n"
    dp = parse_document(raw.encode(), "d3", "notes.txt")
    assert len(dp.paragraphs) == 2


def test_missing_suffix_falls_back_to_text():
    raw = "Just some free text."
    dp = parse_document(raw.encode(), "d4", "unknown.bin")
    assert dp.paragraphs[0] == "Just some free text."


def test_pdf_parsing_gets_paragraphs_and_fields():
    raw = _make_pdf(
        "This agreement is governed by the laws of England and provides for a term of 24 months."
    )
    dp = parse_document(raw, "d5", "agreement.pdf")
    assert dp.document_id == "d5"
    assert len(dp.paragraphs) == 1
    assert "governed by the laws of England" in dp.paragraphs[0]
    assert "term of 24 months" in dp.paragraphs[0]
    assert dp.word_count > 0
    terms = [f.value for f in dp.fields if f.name == "term"]
    assert terms and terms[0] == "24"
