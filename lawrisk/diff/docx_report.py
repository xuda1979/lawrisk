"""Word (.docx) diff report generation from a DiffReport.

Renders the same content as the Markdown report — title, document names,
overall risk line, summary, contract key-facts tables, risk-by-dimension
tables, per-clause change bullets with risk notes and the change ledger —
as a real .docx document via python-docx, returned as raw bytes. Mirrors
`render_markdown`'s signature so the API can produce both formats from one
call site.
"""

from __future__ import annotations

from io import BytesIO
from typing import Dict, List, Mapping, Optional

from docx import Document
from docx.shared import Inches, RGBColor

from lawrisk.diff.differ import DiffOp, DiffReport
from lawrisk.diff.markdown_report import DIM_LABEL, FACT_LABEL
from lawrisk.models import FieldRun, RiskReport

GREEN = RGBColor(0x2E, 0x7D, 0x32)
RED = RGBColor(0xC0, 0x39, 0x2B)
AMBER = RGBColor(0xB8, 0x86, 0x0B)
GREY = RGBColor(0x55, 0x55, 0x55)

_OPS = {"add": "add", "delete": "del", "modify": "mod"}


def _risk_by_para(report: RiskReport) -> Dict[int, List[dict]]:
    """Map a risk report's global paragraph indices to its fired penalties."""
    out: Dict[int, List[dict]] = {}
    for p in report.penalties:
        if p.para_index is None:
            continue
        out.setdefault(p.para_index, []).append(
            {
                "rule_id": p.rule_id,
                "dimension": getattr(p.dimension, "value", str(p.dimension)),
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
        line = f"{r['rule_id']} (+{r['severity']}, {r['dimension']}): {r['reason']}"
        if r.get("mitigation"):
            line += f" — Fix: {r['mitigation']}"
        parts.append(line)
    return "; ".join(parts)


def _excerpt_para(doc, text: str) -> None:
    """Indented italic excerpt paragraph (the verbatim source clause)."""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.4)
    p.paragraph_format.first_line_indent = None
    p.add_run(text).italic = True


def _risk_note_para(doc, text: str) -> None:
    """Indented amber note carrying the penalties that fired on a clause."""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.4)
    run = p.add_run(text)
    run.font.color.rgb = AMBER
    run.italic = True


def _add_change(doc, it, left_map, right_map, label_left, label_right) -> None:
    """One clause-change bullet: op marker + summary + verbatim excerpt(s)."""
    p = doc.add_paragraph(style="List Bullet")
    if it.op is DiffOp.ADD:
        run = p.add_run("[+] added")
        run.bold = True
        run.font.color.rgb = GREEN
        p.add_run("  " + (it.summary or ""))
        excerpt = (it.text_right or "").replace("\n", " ")
        if excerpt:
            _excerpt_para(doc, excerpt)
        return
    if it.op is DiffOp.DELETE:
        run = p.add_run("[-] removed")
        run.bold = True
        run.font.color.rgb = RED
        p.add_run("  " + (it.summary or ""))
        excerpt = (it.text_left or "").replace("\n", " ")
        if excerpt:
            p_ = doc.add_paragraph()
            p_.paragraph_format.left_indent = Inches(0.4)
            del_run = p_.add_run(excerpt)
            del_run.italic = True
            try:
                del_run.font.strike = True
            except Exception:  # pragma: no cover - older python-docx
                pass
        return
    # modify
    run = p.add_run("[~] modified")
    run.bold = True
    run.font.color.rgb = AMBER
    p.add_run("  " + (it.summary or ""))
    lhs = (it.text_left or "").replace("\n", " ")
    rhs = (it.text_right or "").replace("\n", " ")
    if lhs:
        _excerpt_para(doc, "Before: " + lhs)
    if rhs:
        p_ = doc.add_paragraph()
        p_.paragraph_format.left_indent = Inches(0.4)
        p_.add_run("After: ").bold = True
        p_.add_run(rhs).bold = True


def _add_risk_note(doc, it, left_map, right_map, label_left, label_right) -> None:
    """Attach a risk note to a changed clause if any penalties fired on it."""
    left = left_map.get(it.para_index_left, []) if it.para_index_left is not None else []
    right = right_map.get(it.para_index_right, []) if it.para_index_right is not None else []
    if left:
        _risk_note_para(doc, f"⚠ A ({label_left or 'left'}) risk: {_format_risks(left)}")
    if right:
        _risk_note_para(doc, f"⚠ B ({label_right or 'right'}) risk: {_format_risks(right)}")


def _facts_rows(facts: List[Mapping]) -> List[tuple]:
    """Extract found key facts as (label, value, source), deduped by label.

    Accepts dictified FieldRun rows (model_dump()) or FieldRun models.
    Repeated detectors on the same field collapse to the first row so each
    label appears once (matches the Markdown renderer).
    """
    seen: Dict[str, tuple] = {}
    for raw in facts:
        if isinstance(raw, FieldRun):
            row = {
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
        source = (row.get("source") or "").replace("|", "\\|")
        if len(source) > 120:
            source = source[:117] + "…"
        seen[label] = (label, str(row.get("value") or "—"), source)
    return list(seen.values())


def _write_facts_table(doc, rows: List[tuple]) -> None:
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    for i, h in enumerate(("Field", "Value", "Source")):
        table.rows[0].cells[i].text = h
    for label, value, source in rows:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value
        cells[2].text = source


def _dimensions_table(doc, risk: RiskReport, label: str) -> None:
    doc.add_heading(label or "Document", level=3)
    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    for i, h in enumerate(("Dimension", "Score", "Level", "Findings")):
        table.rows[0].cells[i].text = h
    for d in risk.dimensions:
        dim = getattr(d.dimension, "value", d.dimension)
        name = DIM_LABEL.get(str(dim), str(dim))
        n = sum(1 for p in risk.penalties if p.dimension is d.dimension)
        cells = table.add_row().cells
        cells[0].text = name
        cells[1].text = f"{d.normalized:.0f}/100"
        cells[2].text = d.risk_level.value
        cells[3].text = str(n)


def _ledger_table(doc, sections, left_map, right_map, has_risk: bool) -> None:
    doc.add_heading("Change ledger", level=2)
    table = doc.add_table(rows=1, cols=6)
    table.style = "Table Grid"
    for i, h in enumerate(("#", "Op", "Section", "Left¶", "Right¶", "Risk")):
        table.rows[0].cells[i].text = h
    n = 0
    for label, items in sections:
        for it in items:
            n += 1
            left = left_map.get(it.para_index_left, []) if it.para_index_left is not None else []
            right = right_map.get(it.para_index_right, []) if it.para_index_right is not None else []
            cells = table.add_row().cells
            cells[0].text = str(n)
            cells[1].text = _OPS[it.op.value]
            cells[2].text = label[:40]
            cells[3].text = "" if it.para_index_left is None else str(it.para_index_left + 1)
            cells[4].text = "" if it.para_index_right is None else str(it.para_index_right + 1)
            if has_risk:
                cell_parts = []
                if left:
                    cell_parts.append("A:" + ",".join(f"{r['rule_id']}+{r['severity']}" for r in left))
                if right:
                    cell_parts.append("B:" + ",".join(f"{r['rule_id']}+{r['severity']}" for r in right))
                cells[5].text = " · ".join(cell_parts) if cell_parts else "—"
            else:
                cells[5].text = "—"


def render_docx(
    report: DiffReport,
    risk_left: Optional[RiskReport] = None,
    risk_right: Optional[RiskReport] = None,
    facts_left: Optional[List] = None,
    facts_right: Optional[List] = None,
    label_left: str = "Document A",
    label_right: str = "Document B",
) -> bytes:
    """Build the .docx diff report and return it as raw bytes."""
    doc = Document()

    doc.add_heading("Contract Clause Diff Report", level=0)
    doc.add_paragraph(f"Document A: {report.document_left or '(unnamed)'}")
    doc.add_paragraph(f"Document B: {report.document_right or '(unnamed)'}")
    doc.add_paragraph("Engine: local paragraph-level diff (difflib / Myers-style), LLM-free")
    if risk_left is not None and risk_right is not None:
        p = doc.add_paragraph()
        p.add_run("Overall risk: ").bold = True
        p.add_run(
            f"A {risk_left.overall_score}/100 vs B {risk_right.overall_score}/100 — "
            "changed clauses are annotated with the penalties that fired on them."
        )

    doc.add_heading("Summary", level=2)
    doc.add_paragraph(report.summary)

    if facts_left is not None and facts_right is not None:
        left_rows = _facts_rows(facts_left)
        right_rows = _facts_rows(facts_right)
        if left_rows or right_rows:
            doc.add_heading("Contract key facts", level=2)
            doc.add_heading(label_left or "Document A", level=3)
            if left_rows:
                _write_facts_table(doc, left_rows)
            else:
                doc.add_paragraph("No key fields detected.").italic = True
            doc.add_heading(label_right or "Document B", level=3)
            if right_rows:
                _write_facts_table(doc, right_rows)
            else:
                doc.add_paragraph("No key fields detected.").italic = True

    if risk_left is not None and risk_right is not None:
        doc.add_heading("Risk by dimension", level=2)
        _dimensions_table(doc, risk_left, label_left or "Document A")
        _dimensions_table(doc, risk_right, label_right or "Document B")

    left_map = _risk_by_para(risk_left) if risk_left is not None else {}
    right_map = _risk_by_para(risk_right) if risk_right is not None else {}
    has_risk = risk_left is not None or risk_right is not None

    sections = [(n.label, n.items) for n in report.root.children if n.items]
    for label, items in sections:
        doc.add_heading(label, level=2)
        for it in items:
            _add_change(doc, it, left_map, right_map, label_left, label_right)
            if has_risk:
                _add_risk_note(doc, it, left_map, right_map, label_left, label_right)
        doc.add_paragraph()

    if sections:
        _ledger_table(doc, sections, left_map, right_map, has_risk)

    footnote = doc.add_paragraph()
    run = footnote.add_run(
        f"Generated by LawRisk diff engine — {report.stats.additions} additions, "
        f"{report.stats.deletions} deletions, {report.stats.modifications} modifications."
    )
    run.italic = True
    run.font.color.rgb = GREY

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
