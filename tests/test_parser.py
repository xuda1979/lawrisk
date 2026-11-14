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
