"""Paragraph-aligned rows for side-by-side web rendering.

Produces a flat list of rows where the left and right columns line up: each row
points at one paragraph in each document (via global paragraph indices) plus the
diff op and a readable semantic summary. Changed rows are surfaced with
word-level insertions/deletions for inline highlighting.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple

from lawrisk.diff.differ import (
    DiffItem,
    DiffOp,
    DiffReport,
    DiffStats,
    build_diff_tree,
    word_diff,
)
from lawrisk.models import DiffNode, DiffReport as _Report  # noqa: F401


class AlignedRow(NamedTuple):
    op: DiffOp | None
    section: str
    left_idx: int | None
    right_idx: int | None
    left_text: str | None
    right_text: str | None
    summary: str
    left_removed: List[str]
    right_added: List[str]
    right_anchor: int | None = None  # alignment hint (index of right para)
    left_anchor: int | None = None


def _collect_items(root: DiffNode, acc: List[DiffItem]) -> List[DiffItem]:
    for node in root.children:
        acc.extend(node.items)
        _collect_items(node, acc)
    return acc


def aligned_rows(report: DiffReport) -> List[AlignedRow]:
    """Flatten a DiffReport into side-by-side aligned rows spanning only
    paragraphs that actually changed (context rows are added by the frontend).
    """
    items = _collect_items(report.root, [])
    rows: List[AlignedRow] = []
    for it in items:
        left_removed: List[str] = []
        right_added: List[str] = []
        if it.op is DiffOp.MODIFY and it.text_left and it.text_right:
            left_removed, right_added = word_diff(it.text_left, it.text_right)
        rows.append(
            AlignedRow(
                op=it.op,
                section=it.section,
                left_idx=it.para_index_left,
                right_idx=it.para_index_right,
                left_text=it.text_left,
                right_text=it.text_right,
                summary=it.summary,
                left_removed=left_removed,
                right_added=right_added,
                left_anchor=it.para_index_left,
                right_anchor=it.para_index_right,
            )
        )
    # Deterministic ordering: by left index when present, else by right index.
    rows.sort(key=lambda r: (r.left_idx if r.left_idx is not None else 10**9,
                             r.right_idx if r.right_idx is not None else 10**9))
    return rows


def build_aligned_rows(
    paragraphs_left: List[str],
    paragraphs_right: List[str],
    document_left: str,
    document_right: str,
) -> List[AlignedRow]:
    report = build_diff_tree(paragraphs_left, paragraphs_right, document_left, document_right)
    return aligned_rows(report)


def to_dict(row: AlignedRow) -> Dict[str, object]:
    return {
        "op": row.op.value if row.op else "context",
        "section": row.section,
        "leftIdx": row.left_idx,
        "rightIdx": row.right_idx,
        "leftText": row.left_text,
        "rightText": row.right_text,
        "summary": row.summary,
        "leftRemoved": row.left_removed,
        "rightAdded": row.right_added,
    }
