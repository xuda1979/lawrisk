"""P1: clause diff tree tests (AC3, AC4)."""

from __future__ import annotations

from pathlib import Path

from lawrisk.diff.differ import (
    DiffOp,
    build_diff_tree,
    diff_texts,
    split_sections,
    word_diff,
)
from lawrisk.diff.markdown_report import render_markdown
from lawrisk.diff.sidebyside import aligned_rows, to_dict
from lawrisk.parser import parse_document

FIXTURES = Path(__file__).parent / "fixtures"


def _load_pair(a: str, b: str):
    la = parse_document((FIXTURES / f"{a}.docx").read_bytes(), a, f"{a}.docx")
    rb = parse_document((FIXTURES / f"{b}.docx").read_bytes(), b, f"{b}.docx")
    report = build_diff_tree(la.paragraphs, rb.paragraphs, a, b)
    return la, rb, report


class TestDiffTreeStructure:
    """AC3: correct tree with 30+ differences in the provided fixture."""

    def test_fixture_has_over_30_differences(self):
        _, _, report = _load_pair("diff_template_x", "diff_template_y")
        total = (
            report.stats.additions
            + report.stats.deletions
            + report.stats.modifications
        )
        assert total >= 30

    def test_tree_is_organized_by_section(self):
        _, _, report = _load_pair("diff_template_x", "diff_template_y")
        assert report.root.children
        labels = [c.label for c in report.root.children]
        # e.g. section 2 paired across both docs:
        assert any("Definitions" in lb for lb in labels)
        assert all(isinstance(c.items, list) for c in report.root.children)

    def test_all_ops_marked(self):
        _, _, report = _load_pair("diff_template_x", "diff_template_y")
        ops = {i.op for node in report.root.children for i in node.items}
        assert DiffOp.MODIFY in ops
        assert DiffOp.ADD in ops

    def test_delete_path_also_works(self):
        # template_b has paragraphs removed vs template_c.
        _, _, report = _load_pair("template_b", "template_c")
        ops = {i.op for node in report.root.children for i in node.items}
        assert DiffOp.DELETE in ops or DiffOp.MODIFY in ops


class TestDiffSemantics:
    """AC4: readable summaries and index accuracy."""

    def test_summaries_are_readable_and_nonempty(self):
        _, _, report = _load_pair("diff_template_x", "diff_template_y")
        items = [i for node in report.root.children for i in node.items]
        assert len(items) >= 30
        for it in items:
            assert it.summary and it.summary.strip()
            assert len(it.summary) > 8

    def test_paragraph_indices_point_to_source_text(self):
        la, rb, report = _load_pair("diff_template_x", "diff_template_y")
        for node in report.root.children:
            for it in node.items:
                if it.op is DiffOp.MODIFY:
                    assert la.paragraphs[it.para_index_left] == it.text_left
                    assert rb.paragraphs[it.para_index_right] == it.text_right
                elif it.op is DiffOp.DELETE:
                    assert la.paragraphs[it.para_index_left] == it.text_left
                elif it.op is DiffOp.ADD:
                    assert rb.paragraphs[it.para_index_right] == it.text_right

    def test_word_diff_produces_inline_markers(self):
        removed, added = word_diff(
            "The Provider retains ownership of intellectual property.",
            "Provider grants Customer ownership of all IP.",
        )
        assert removed and added

    def test_added_section_appears(self):
        # template_b has an extra paragraph vs template_a; plus fixture X lacks
        # some Y subsections => additions.
        _, _, report = _load_pair("template_a", "template_b")
        adds = [i for n in report.root.children for i in n.items if i.op is DiffOp.ADD]
        assert adds


class TestDiffRendering:
    def test_markdown_report_contains_ledger(self):
        _, _, report = _load_pair("diff_template_x", "diff_template_y")
        md = render_markdown(report)
        assert "Change ledger" in md
        assert "[+]" in md
        assert "[~]" in md
        assert "paragraph" in md

    def test_aligned_rows_and_dict(self, load_docx):
        la = load_docx("template_a")
        rb = load_docx("template_b")
        report = build_diff_tree(la.paragraphs, rb.paragraphs, "A", "B")
        rows = aligned_rows(report)
        assert rows
        d = to_dict(rows[0])
        assert set(["op", "leftText", "rightText", "summary"]).issubset(d)

    def test_plain_text_diff_api(self):
        text = [
            "First paragraph of the agreement.",
            "Second paragraph discussing termination rights.",
            "Third paragraph about fees of $1,000.",
        ]
        modified = [
            "First paragraph of the agreement.",
            "Second paragraph discussing **termination and renewal** rights.",
            "New paragraph introducing data processing terms.",
        ]
        report = diff_texts("\n\n".join(text), "\n\n".join(modified), "L", "R")
        assert report.stats.modifications >= 1 or report.stats.additions >= 1


class TestSectionSplit:
    def test_split_detects_headings(self, load_docx):
        la = load_docx("template_a")
        sections = split_sections(la.paragraphs)
        assert any("Article" in s.heading for s in sections)
