"""P3: bundled clause-template library tests."""

from __future__ import annotations

from lawrisk.templates import (
    diff_against_template,
    get_template,
    list_templates,
)


def test_library_has_multiple_templates():
    tpls = list_templates()
    assert len(tpls) >= 3
    ids = {t.id for t in tpls}
    assert {"msa", "sps", "nda"}.issubset(ids)


def test_lookup_by_id():
    tpl = get_template("msa")
    assert tpl is not None
    assert tpl.name
    assert tpl.paragraphs
    assert tpl.sections
    assert tpl.to_dict()["paragraph_count"] == len(tpl.paragraphs)


def test_unknown_template_returns_none():
    assert get_template("does-not-exist") is None


def test_content_hash_is_deterministic():
    a = get_template("msa")
    b = get_template("msa")
    assert a.content_hash == b.content_hash
    assert len(a.content_hash) == 64


def test_diff_against_template_produces_report():
    doc = [
        "This agreement shall automatically renew each year.",
        "Provider may terminate for any reason at any time.",
        "Customer shall pay a setup fee of $5,000 on signature.",
    ]
    report = diff_against_template(doc, "msa", document_name="Doc")
    assert report.document_right == "Doc"
    assert report.root.children
    assert report.stats.additions + report.stats.deletions + report.stats.modifications > 0


def test_diff_against_unknown_template_raises():
    import pytest

    with pytest.raises(KeyError):
        diff_against_template(["a"], "nope", document_name="Doc")
