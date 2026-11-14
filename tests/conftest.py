"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from lawrisk.parser import parse_document
from lawrisk.rules import score_document

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def score_docx() -> Callable:
    """Score a fixture DOCX by name; returns its RiskReport."""

    def _score(name: str, document_id: str | None = None):
        data = (FIXTURES / f"{name}.docx").read_bytes()
        dp = parse_document(data, document_id or name, f"{name}.docx")
        return score_document(dp.paragraphs, dp.document_id)

    return _score


@pytest.fixture
def load_docx() -> Callable:
    """Parse a fixture DOCX by name; returns its DocParse."""

    def _load(name: str):
        data = (FIXTURES / f"{name}.docx").read_bytes()
        return parse_document(data, name, f"{name}.docx")

    return _load
