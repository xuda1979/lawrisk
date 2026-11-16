"""Key-biz-field extraction from paragraphs (the 'module 06' slice for this project).

Each detector runs over (index, text) pairs and returns FieldRun rows with the
verbatim source excerpt so findings stay explainable and traceable.
"""

from __future__ import annotations

import re
from typing import Callable, List, Pattern

from lawrisk.models import DocParse, FieldRun


def _find(pattern: Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(0) if m else None


CurrencyDetector: Pattern[str] = re.compile(
    r"\$\s?[\d,]+(?:\.\d{2})?|\d[\d,]*\.?\d*\s*(?:USD|EUR|RMB|HKD|GBP)\b",
    re.IGNORECASE,
)
TermYearsDetector: Pattern[str] = re.compile(
    # The gap between the term keyword and the number must not swallow
    # digits: "term of 120 months" would otherwise match "0" after the
    # greedy window consumed "12".
    r"(?:term\s+of|for\s+a\s+term|initial\s+term)[^\n\d]{0,20}(\d+)\s*(?:year|month)s?",
    re.IGNORECASE,
)
GoverningLawDetector: Pattern[str] = re.compile(
    r"govern(?:ed|ing)?\s+(?:by|under)\s+(?:the\s+)?(?:laws?\s+of\s+)?"
    r"([A-Za-z]{2,}(?:\s+[A-Za-z]{2,}){0,3})",
    re.IGNORECASE,
)
ArbitrationDetector: Pattern[str] = re.compile(
    r"arbitrat(?:ion|e)\s+(?:shall\s+)?(?:be\s+)?(?:conducted\s+)?(?:at|in|under)"
    r"([^\.,;]{0,40})",
    re.IGNORECASE,
)


def _extract(paras: List[str], text: str) -> List[FieldRun]:
    runs: List[FieldRun] = []
    # Global pre-checks avoid scanning every paragraph when the doc lacks a
    # signal. Currency is gated on its own regex, not the word "currency":
    # "pay $100,000 in installments" contains no literal currency word yet is
    # a perfectly detectable currency fact.
    has_currency = bool(re.search(CurrencyDetector, text))
    has_term = "term" in text.casefold()
    has_govern = "govern" in text.casefold()
    has_arbitr = "arbitr" in text.casefold()
    for i, p in enumerate(paras):
        if has_currency:
            if m := CurrencyDetector.search(p):
                runs.append(FieldRun(name="currency", value=m.group(0)[:60], source=p[:300], para_index=i, found=True))
        if has_term:
            if m := TermYearsDetector.search(p):
                runs.append(FieldRun(name="term", value=m.group(1), source=p[:300], para_index=i, found=True))
        if has_govern:
            if m := GoverningLawDetector.search(p):
                runs.append(FieldRun(name="governing_law", value=m.group(1)[:60], source=p[:300], para_index=i, found=True))
        if has_arbitr:
            if m := ArbitrationDetector.search(p):
                runs.append(FieldRun(name="arbitration", value=m.group(1).strip()[:60], source=p[:300], para_index=i, found=True))
    return runs


def extract_fields(paras: List[str], text: str) -> List[FieldRun]:
    """Run all field detectors; returns found fields (empty list if none)."""
    runs = _extract(paras, text)
    return [r for r in runs if r.found]
