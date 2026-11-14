"""Shared text utilities: paragraph extraction, normalisation, heading detection."""

from __future__ import annotations

import re
from typing import List


_WS_RE = re.compile(r"\s+")
HEADING_RE = re.compile(
    r"^\s*"
    r"(?:"
    r"ARTICLE[.\-\s]+[0-9IVXLC]+|"
    r"SECTION[.\-\s]+[0-9IVXLC]+|"
    r"\d+\.\d*\s+[A-Z]|"
    r"第\s*[一二三四五六七八九十百\d]+\s*(?:条|章)"
    r")",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """Canonical normalisation used for deterministic compare tokens."""
    if text is None:
        return ""
    t = text.casefold()
    t = _WS_RE.sub(" ", t)
    return t.strip()


def split_paragraphs(text: str) -> List[str]:
    """Split raw document text into non-empty paragraphs."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\r\n\r\n", text)]
    return [p for p in paras if p]


def looks_like_heading(text: str, prev: str | None = None) -> bool:
    """Heuristics: numbered section/title patterns, or short lines before a blank."""
    t = text.strip()
    if not t:
        return False
    if len(t) > 80:
        return False
    if HEADING_RE.match(t):
        return True
    if re.match(r"^[A-Z0-9][A-Z0-9 _/:&-]{1,40}$", t) and len(t) <= 60:
        return True
    return False
