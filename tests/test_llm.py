"""P3: LLM enhancement layer tests (mock is deterministic; provider is pluggable)."""

from __future__ import annotations

from lawrisk import llm
from lawrisk.llm import MockSummarizer, get_provider, register_provider


def test_mock_summary_phrases():
    s = MockSummarizer()
    assert s.summarize_clause(None, "an indemnity clause", "add") == (
        "Added an indemnity clause (LLM mock summary)."
    )
    assert s.summarize_clause("the old clause", None, "delete") == (
        "Removed the old clause (LLM mock summary)."
    )
    assert s.summarize_clause("a", "b", "modify").startswith("Revised a clause")
    assert s.summarize_clause(None, None, "modify") == "Clause changed (LLM mock summary)."


def test_provider_registry_builds():
    p = get_provider("mock")
    assert isinstance(p, MockSummarizer)


def test_custom_provider_can_be_registered():
    class MySummarizer(MockSummarizer):
        name = "my-special"

    register_provider(MySummarizer)
    p = get_provider("my-special")
    assert isinstance(p, MySummarizer)


def test_report_summary_mentions_counts():
    class _S:
        additions = 3
        deletions = 1
        modifications = 2

    s = MockSummarizer()
    text = s.summarize_report(_S(), [])
    assert "6" in text and "3 added" in text and "1 removed" in text


def test_layer_description_returns_provider():
    desc = llm.describe_layer()
    assert desc["provider"] in {"mock", "custom"}

    # with LLM off (default) the layer is always deterministic
    assert desc["deterministic"] is True
