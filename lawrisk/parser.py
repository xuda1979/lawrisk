"""Document ingestion: DOCX / PDF / TXT to a structured DocParse."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import List

from lawrisk.fields import extract_fields
from lawrisk.models import DocParse
from lawrisk.textutil import looks_like_heading, split_paragraphs


def _read_text_from_pdf(data: bytes) -> str:
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    except Exception:  # pragma: no cover - defensive fallback
        return ""


def _read_text_from_docx(data: bytes) -> str:
    import docx

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        document = docx.Document(tmp_path)
        blocks: List[str] = []
        last_empty = True
        for para in document.paragraphs:
            t = para.text.strip()
            if t:
                blocks.append(t)
                last_empty = False
            elif not last_empty:
                blocks.append("")
                last_empty = True
        text = "\n\n".join(blocks)
        for table in document.tables:
            for row in table.rows:
                row_txt = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                if row_txt:
                    text += "\n\n" + row_txt
        return text
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def parse_document(data: bytes, document_id: str, filename: str = "") -> DocParse:
    suffix = Path(filename).suffix.lower() if filename else ""
    if suffix == ".pdf":
        raw = _read_text_from_pdf(data)
    elif suffix == ".docx":
        raw = _read_text_from_docx(data)
    else:
        raw = data.decode("utf-8", errors="replace")

    paragraphs = split_paragraphs(raw)
    headings = [
        i
        for i, p in enumerate(paragraphs)
        if looks_like_heading(p)
    ]
    full = "\n".join(paragraphs)
    fields = extract_fields(paragraphs, full)
    return DocParse(
        document_id=document_id,
        paragraphs=paragraphs,
        headings=headings,
        fields=fields,
        word_count=len(full.split()),
    )
