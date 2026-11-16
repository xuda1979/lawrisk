"""Markdown diff report generation from a DiffReport.

Produces a readable, self-contained Markdown document summarising the diff tree:
a stats block, a section-by-section change list with +/- markers and semantic
summaries, then a compact change-ledger at the end. When the caller supplies
the two RiskReports, every changed clause is annotated with the risk penalties
that fired on its source paragraph(s), so the report shows *why* a change is
risky — not just what changed.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional

from lawrisk.diff.differ import DiffOp, DiffReport
from lawrisk.models import FieldRun, RiskReport

# Display labels match the frontend FactsPanel (frontend/src/components/FactsPanel.tsx).
FACT_LABEL: Dict[str, str] = {
    "currency": "Currency",
    "term": "Term",
    "governing_law": "Governing law",
    "arbitration": "Arbitration seat",
}

# Long-form dimension names for the risk-by-dimension table.
DIM_LABEL: Dict[str, str] = {
    "commercial": "Commercial risk",
    "liability": "Liability / legal risk",
    "data": "Data protection",
    "export": "Export compliance",
}


def _bullet(it, max_excerpt: int = 260) -> str:
    if it.op is DiffOp.ADD:
        excerpt = (it.text_right or "")[:max_excerpt].replace("\n", " ")
        return f"`[+] added`  {it.summary}\n\n> {excerpt}" if excerpt else f"`[+] added`  {it.summary}"
    if it.op is DiffOp.DELETE:
        excerpt = (it.text_left or "")[:max_excerpt].replace("\n", " ")
        return f"`[-] removed`  {it.summary}\n\n> ~~{excerpt}~~" if excerpt else f"`[-] removed`  {it.summary}"
    # modify
    lhs = (it.text_left or "").replace("\n", " ")
    rhs = (it.text_right or "").replace("\n", " ")
    block = f"\n\n> ~~{lhs[:max_excerpt]}~~  \n> **{rhs[:max_excerpt]}**"
    return f"`[~] modified`  {it.summary}{block}"


def _risk_by_para(report: RiskReport) -> Dict[int, List[dict]]:
    """Map a risk report's global paragraph indices to its fired penalties."""
    out: Dict[int, List[dict]] = {}
    for p in report.penalties:
        if p.para_index is None:
            continue
        out.setdefault(p.para_index, []).append(
            {
                "rule_id": p.rule_id,
                "dimension": p.dimension,
                "severity": p.severity,
                "reason": p.reason,
                "mitigation": p.mitigation,
            }
        )
    return out


def _format_risks(risks: List[dict]) -> str:
    """One compact line per penalty:
    `R-COMM-1 (+20, commercial): reason — Fix: mitigation`.
    """
    parts = []
    for r in risks:
        dim = r["dimension"]
        dim = getattr(dim, "value", dim)
        line = f"**{r['rule_id']}** (+{r['severity']}, {dim}): {r['reason']}"
        if r.get("mitigation"):
            line += f" — Fix: {r['mitigation']}"
        parts.append(line)
    return "; ".join(parts)


def _item_risks(it, left_map, right_map):
    """(left_risks, right_risks) penalties that fired on this change's paragraphs."""
    left = left_map.get(it.para_index_left, []) if it.para_index_left is not None else []
    right = right_map.get(it.para_index_right, []) if it.para_index_right is not None else []
    return left, right


def _risk_note(it, left_map, right_map, label_left: str, label_right: str) -> str:
    """Blockquote line(s) attaching risk to a changed clause, if any fired."""
    left, right = _item_risks(it, left_map, right_map)
    parts = []
    if left:
        parts.append(f"**A ({label_left or 'left'}) risk:** {_format_risks(left)}")
    if right:
        parts.append(f"**B ({label_right or 'right'}) risk:** {_format_risks(right)}")
    if not parts:
        return ""
    return "\n\n".join(f"> ⚠ {p}" for p in parts)


def _facts_table(facts: List[Mapping]) -> str:
    """Render found contract key facts as a Markdown table, deduped by name.

    Accepts dictified FieldRun rows (model_dump()) or FieldRun models. Only
    `found` facts are shown; repeated detectors on the same field collapse to
    the first row so each label appears once.
    """
    seen: Dict[str, dict] = {}
    for raw in facts:
        if isinstance(raw, FieldRun):
            row: Mapping = {
                "name": raw.name,
                "value": raw.value,
                "source": raw.source,
                "found": raw.found,
            }
        else:
            row = raw
        if not row.get("found", True):
            continue
        label = FACT_LABEL.get(str(row.get("name")), str(row.get("name")))
        if label in seen:
            continue
        seen[label] = dict(row)
    if not seen:
        return ""
    lines = ["| Field | Value | Source |", "|-------|-------|--------|"]
    for label, row in seen.items():
        value = (row.get("value") or "—").replace("|", "\\|")
        source = (row.get("source") or "").replace("|", "\\|")
        if len(source) > 120:
            source = source[:117] + "…"
        lines.append(f"| {label} | {value} | “{source}” |")
    return "\n".join(lines)


def _dimensions_table(risk: RiskReport, label: str) -> str:
    """Render one document's per-dimension scores as a Markdown table."""
    lines = [f"### {label or 'Document'}", "", "| Dimension | Score | Level | Findings |", "|-----------|-------|-------|----------|"]
    for d in risk.dimensions:
        dim = getattr(d.dimension, "value", d.dimension)
        name = DIM_LABEL.get(str(dim), str(dim))
        n = sum(1 for p in risk.penalties if p.dimension is d.dimension)
        lines.append(
            f"| {name} | {d.normalized:.0f}/100 | {d.risk_level.value} | {n} |"
        )
    return "\n".join(lines)


def render_markdown(
    report: DiffReport,
    risk_left: Optional[RiskReport] = None,
    risk_right: Optional[RiskReport] = None,
    facts_left: Optional[List] = None,
    facts_right: Optional[List] = None,
    label_left: str = "Document A",
    label_right: str = "Document B",
) -> str:
    lines: List[str] = []
    lines.append(f"# Contract Clause Diff Report")
    lines.append("")
    lines.append(f"- **Document A:** {report.document_left or '(unnamed)'}")
    lines.append(f"- **Document B:** {report.document_right or '(unnamed)'}")
    lines.append("- **Engine:** local paragraph-level diff (difflib / Myers-style), LLM-free")
    if risk_left is not None and risk_right is not None:
        lines.append(
            f"- **Overall risk:** A {risk_left.overall_score}/100 vs "
            f"B {risk_right.overall_score}/100 — changed clauses are annotated "
            "with the penalties that fired on them."
        )
    lines.append("")
    lines.append(f"## Summary")
    lines.append("")
    lines.append(report.summary)
    lines.append("")

    if facts_left is not None and facts_right is not None:
        left_table = _facts_table(facts_left)
        right_table = _facts_table(facts_right)
        if left_table or right_table:
            lines.append(f"## Contract key facts")
            lines.append("")
            lines.append(f"### {label_left or 'Document A'}")
            lines.append("")
            lines.append(left_table or "_No key fields detected._")
            lines.append("")
            lines.append(f"### {label_right or 'Document B'}")
            lines.append("")
            lines.append(right_table or "_No key fields detected._")
            lines.append("")

    if risk_left is not None and risk_right is not None:
        lines.append("## Risk by dimension")
        lines.append("")
        lines.append(_dimensions_table(risk_left, label_left or "Document A"))
        lines.append("")
        lines.append(_dimensions_table(risk_right, label_right or "Document B"))
        lines.append("")

    left_map = _risk_by_para(risk_left) if risk_left is not None else {}
    right_map = _risk_by_para(risk_right) if risk_right is not None else {}
    has_risk = risk_left is not None or risk_right is not None

    sections = [(n.label, n.items) for n in report.root.children if n.items]
    for label, items in sections:
        lines.append(f"## {label}")
        lines.append("")
        for it in items:
            lines.append(_bullet(it, max_excerpt=220))
            if has_risk:
                note = _risk_note(it, left_map, right_map, label_left, label_right)
                if note:
                    lines.append("")
                    lines.append(note)
            lines.append("")

    lines.append("---")
    lines.append("## Change ledger")
    lines.append("")
    lines.append("| # | Op | Section | Left¶ | Right¶ | Risk |")
    lines.append("|---|----|---------|-------|--------|------|")
    n = 0
    for label, items in sections:
        for it in items:
            n += 1
            lp = "" if it.para_index_left is None else it.para_index_left + 1
            rp = "" if it.para_index_right is None else it.para_index_right + 1
            op = {"add": "add", "delete": "del", "modify": "mod"}[it.op.value]
            if has_risk:
                left, right = _item_risks(it, left_map, right_map)
                cell_parts = []
                if left:
                    cell_parts.append("A:" + ",".join(f"{r['rule_id']}+{r['severity']}" for r in left))
                if right:
                    cell_parts.append("B:" + ",".join(f"{r['rule_id']}+{r['severity']}" for r in right))
                risk_cell = " · ".join(cell_parts) if cell_parts else "—"
            else:
                risk_cell = "—"
            lines.append(
                f"| {n} | {op} | `{label[:40]}` | {lp} | {rp} | {risk_cell} |"
            )
    lines.append("")
    lines.append(
        f"_Generated by LawRisk diff engine — {report.stats.additions} additions, "
        f"{report.stats.deletions} deletions, {report.stats.modifications} modifications._"
    )
    return "\n".join(lines)
