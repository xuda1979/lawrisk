"""Optional LLM enhancement layer (P3).

Design
------
* OFF by default. Unless the environment variable ``LAWRISK_LLM=1`` is set, all
  summarisation routes use the deterministic :class:`MockSummarizer` so the
  whole pipeline stays local, offline and reproducible.
* When enabled, :func:`get_provider` returns a pluggable provider built via the
  ``LAWRISK_LLM_PROVIDER`` env var (built-ins: ``mock``; extend by subclassing
  :class:`Summarizer`). A real implementation would call an HTTP endpoint; the
  interface stays a pure function of ``(left, right, op)`` so callers never
  touch the network themselves.

Both providers are deterministic for identical inputs, preserving AC1.
"""

from __future__ import annotations

import os
import re
from typing import List

ENABLED = os.environ.get("LAWRISK_LLM", "0").lower() in {"1", "true", "yes"}
PROVIDER_NAME = os.environ.get("LAWRISK_LLM_PROVIDER", "mock").lower()


class Summarizer:
    """Pluggable summarisation provider interface."""

    name = "base"

    def summarize_clause(
        self, text_left: str | None, text_right: str | None, op: str
    ) -> str:
        """Return a one-line semantic summary for one diff item."""
        raise NotImplementedError

    def summarize_report(self, stats, counts: List[str]) -> str:
        """Return a paragraph-level summary for the whole report."""
        raise NotImplementedError


def _preview(t: str | None, n: int = 90) -> str:
    if not t:
        return ""
    clean = re.sub(r"\s+", " ", t).strip()
    return clean if len(clean) <= n else clean[: n - 1] + "…"


class MockSummarizer(Summarizer):
    """Deterministic mock: template sentences phrased from op + preview."""

    name = "mock"

    def summarize_clause(
        self, text_left: str | None, text_right: str | None, op: str
    ) -> str:
        left, right = _preview(text_left), _preview(text_right)
        if op == "add":
            return f"Added {right or 'a new clause'} (LLM mock summary)."
        if op == "delete":
            return f"Removed {left or 'a clause'} (LLM mock summary)."
        if right and left:
            return f"Revised a clause from '{left}' to '{right}' (LLM mock summary)."
        return "Clause changed (LLM mock summary)."

    def summarize_report(self, stats, _counts: List[str]) -> str:
        total = stats.additions + stats.deletions + stats.modifications
        return (
            f"{total} paragraph-level change(s) detected: {stats.additions} added, "
            f"{stats.deletions} removed, {stats.modifications} modified."
        )


class _ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, type[Summarizer]] = {
            MockSummarizer.name: MockSummarizer,
        }

    def register(self, cls: type[Summarizer]) -> None:
        self._providers[cls.name] = cls

    def build(self, name: str) -> Summarizer:
        cls = self._providers.get(name or "mock")
        if cls is None:
            raise ValueError(f"unknown LLM provider: {name!r}")
        return cls()


registry = _ProviderRegistry()


def get_provider(name: str | None = None) -> Summarizer:
    """Build the active summariser from the registry.

    An explicit ``name`` always wins (used by tests to force a provider). With
    no explicit name, the ``LAWRISK_LLM_PROVIDER`` env var is used only when
    LLM mode is enabled; otherwise the deterministic mock is returned so output
    stays stable when the layer is off.
    """
    if name is not None:
        return registry.build(name)
    requested = PROVIDER_NAME if ENABLED else "mock"
    return registry.build(requested)


# Module-level singleton used by the API layer.
ACTIVE = get_provider()


def register_provider(cls: type[Summarizer]) -> type[Summarizer]:
    """Decorator to register a custom provider at import time."""
    registry.register(cls)
    return cls


# Backwards-compatible module-level helpers (used by tests / API).
def summarize_clause(text_left: str | None, text_right: str | None, op: str) -> str:
    return ACTIVE.summarize_clause(text_left, text_right, op)


def summarize_report(stats, counts: List[str]) -> str:
    return ACTIVE.summarize_report(stats, counts)


def describe_layer() -> dict[str, object]:
    return {
        "enabled": ENABLED,
        "provider": ACTIVE.name,
        "deterministic": ACTIVE.name == "mock",
    }
