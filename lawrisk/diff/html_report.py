"""Self-contained HTML diff report generation.

Mirrors ``lawrisk.diff.markdown_report.render_markdown`` section-for-section
(the doc names + overall-risk header, summary, contract key facts, risk by
dimension, per-section change list with risk notes, highest-risk clauses,
risk by section, change ledger and footer stats) but rendered as a single
standalone HTML document with inline CSS. Everything is HTML-entity escaped
and there is zero external dependency, so the file opens in any browser and
is safe to email or archive.

The document content is escaped with ``html.escape``; the only markup we
emit ourselves are the structural tags (headings, tables, blockquotes) and
the diff glyphs, so the output is always well-formed and can never execute
scripts from the input documents.
"""

from __future__ import annotations

from html import escape
from typing import Dict, List, Mapping, Optional

from lawrisk.diff.differ import DiffOp, DiffReport
from lawrisk.models import FieldRun, RiskReport

# Same display labels as the Markdown renderer (and the frontend panels).
FACT_LABEL: Dict[str, str] = {
    "currency": "Currency",
    "term": "Term",
    "governing_law": "Governing law",
    "arbitration": "Arbitration seat",
}

DIM_LABEL: Dict[str, str] = {
    "commercial": "Commercial risk",
    "liability": "Liability / legal risk",
    "data": "Data protection",
    "export": "Export compliance",
}

_CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  margin:0;background:#f7f7f9;color:#1c2330;line-height:1.55;font-size:14px}
.wrap{max-width:1000px;margin:0 auto;padding:28px 24px 72px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:26px 0 8px;padding-bottom:4px;border-bottom:2px solid #e2e5ea}
h3{font-size:15px;margin:16px 0 6px} h4{font-size:13.5px;margin:14px 0 4px}
.docmeta{color:#5c6470;font-size:13px;margin:0 0 2px}
.riskline{font-weight:600;color:#1c2330;margin:8px 0 0}
.summary{margin:8px 0 0;color:#1c2330}
table{border-collapse:collapse;width:100%;margin:8px 0 14px;font-size:13px}
th,td{border:1px solid #e2e5ea;padding:6px 9px;text-align:left;vertical-align:top}
th{background:#eef1f6;font-weight:600}
tr:nth-child(even) td{background:#fafbfd}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
.section{margin:18px 0 0}
.clause{border:1px solid #e2e5ea;border-radius:8px;padding:10px 12px;margin:0 0 10px;font-size:13px;background:#fff}
.clause .head{font-weight:600;margin:0 0 6px}
.clause .excerpt{margin:4px 0 0;color:#3a4252;white-space:pre-wrap;word-break:break-word}
.clause .excerpt.removed{color:#a3312a;text-decoration:line-through}
.clause .excerpt.added{color:#17693a}
.risks{margin:8px 0 0;border-left:3px solid #e0b34a;background:#fff8e8;padding:6px 9px;border-radius:0 6px 6px 0;font-size:12.5px}
.risks .side{margin:2px 0}
.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:11px;font-weight:700;text-transform:uppercase}
.pill.add{background:#e3f4e8;color:#17693a}.pill.del{background:#fbe5e2;color:#a3312a}.pill.mod{background:#fff2cc;color:#8a6d00}
.note{color:#5c6470;font-size:13px;margin:4px 0}
.ranked{margin:4px 0 12px}
.ranked .clause{background:#fdfaf2}
.footer{margin-top:30px;padding-top:10px;border-top:1px solid #e2e5ea;color:#5c6470;font-size:12px}
""".strip()


def _h(text: str) -> str:
    return escape(text, quote=False)


def _bullet(it, max_excerpt: int = 220) -> str:
    """HTML block for one changed clause."""
    if it.op is DiffOp.ADD:
        excerpt = (it.text_right or "")[:max_excerpt]
        glyph = "add"
        label = "[+] added"
        excerpt_html = f'<p class="excerpt added">{_h(excerpt)}</p>' if excerpt else ""
    elif it.op is DiffOp.DELETE:
        excerpt = (it.text_left or "")[:max_excerpt]
        glyph = "del"
        label = "[&minus;] removed"
        excerpt_html = f'<p class="excerpt removed">{_h(excerpt)}</p>' if excerpt else ""
    else:
        lhs = (it.text_left or "")[:max_excerpt]
        rhs = (it.text_right or "")[:max_excerpt]
        glyph = "mod"
        label = "[~] modified"
        excerpt_parts = []
        if lhs:
            excerpt_parts.append(f'<p class="excerpt removed">{_h(lhs)}</p>')
        if rhs:
            excerpt_parts.append(f'<p class="excerpt added">{_h(rhs)}</p>')
        excerpt_html = "".join(excerpt_parts)
    return (
        f'<div class="clause"><p class="head">'
        f'<span class="pill {glyph}">{label}</span> {_h(it.summary)}</p>{excerpt_html}'
    )


def _risk_by_para(report: RiskReport) -> Dict[int, List[dict]]:
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
    """Compact single-line rendering of one penalty list."""
    parts = []
    for r in risks:
        dim = r["dimension"]
        dim = getattr(dim, "value", dim)
        line = f"{r['rule_id']} (+{r['severity']}, {dim}): {r['reason']}"
        if r.get("mitigation"):
            line += f" — Fix: {r['mitigation']}"
        parts.append(line)
    return _h("; ".join(parts))


def _item_risks(it, left_map, right_map):
    left = left_map.get(it.para_index_left, []) if it.para_index_left is not None else []
    right = right_map.get(it.para_index_right, []) if it.para_index_right is not None else []
    return left, right


def _risk_note(it, left_map, right_map, label_left: str, label_right: str) -> str:
    """HTML blockquote attaching risk penalties to a changed clause, if any."""
    left, right = _item_risks(it, left_map, right_map)
    parts = []
    if left:
        parts.append(
            f'<div class="side"><b>A ({_h(label_left or "left")}) risk:</b> '
            f"{_format_risks(left)}</div>"
        )
    if right:
        parts.append(
            f'<div class="side"><b>B ({_h(label_right or "right")}) risk:</b> '
            f"{_format_risks(right)}</div>"
        )
    if not parts:
        return ""
    return '<div class="risks">' + "".join(parts) + "</div>"


def _top_risky_clauses(sections, left_map, right_map, n: int = 5):
    ranked = []
    for label, items in sections:
        for it in items:
            left, right = _item_risks(it, left_map, right_map)
            total = sum(r["severity"] for r in left) + sum(r["severity"] for r in right)
            if total:
                ranked.append((label, it, total))
    ranked.sort(key=lambda t: t[2], reverse=True)
    return ranked[:n]


def _risk_by_section(sections, left_map, right_map):
    rows = []
    for label, items in sections:
        left_pts = right_pts = 0
        for it in items:
            left, right = _item_risks(it, left_map, right_map)
            left_pts += sum(r["severity"] for r in left)
            right_pts += sum(r["severity"] for r in right)
        if left_pts or right_pts:
            rows.append((label, left_pts, right_pts, left_pts + right_pts))
    rows.sort(key=lambda t: t[3], reverse=True)
    return rows


def _facts_table(facts: List[Mapping]) -> str:
    """HTML table of found contract key facts, deduped by label."""
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
    cells = ["<table><thead><tr><th>Field</th><th>Value</th><th>Source</th></tr></thead><tbody>"]
    for label, row in seen.items():
        value = (row.get("value") or "—")
        source = (row.get("source") or "")
        if len(source) > 120:
            source = source[:117] + "…"
        cells.append(
            f"<tr><td>{_h(label)}</td><td>{_h(value)}</td>"
            f"<td><em>&ldquo;{_h(source)}&rdquo;</em></td></tr>"
        )
    cells.append("</tbody></table>")
    return "".join(cells)


def _dimensions_table(risk: RiskReport, label: str) -> str:
    """HTML table of one document's per-dimension scores."""
    head = f"<h3>{_h(label or 'Document')}</h3>"
    rows = ["<table><thead><tr><th>Dimension</th><th>Score</th>"
            "<th>Level</th><th>Findings</th></tr></thead><tbody>"]
    for d in risk.dimensions:
        dim = getattr(d.dimension, "value", d.dimension)
        name = DIM_LABEL.get(str(dim), str(dim))
        n = sum(1 for p in risk.penalties if p.dimension is d.dimension)
        rows.append(
            f"<tr><td>{_h(name)}</td><td>{d.normalized:.0f}/100</td>"
            f"<td>{_h(d.risk_level.value)}</td><td>{n}</td></tr>"
        )
    rows.append("</tbody></table>")
    return head + "".join(rows)


def render_html(
    report: DiffReport,
    risk_left: Optional[RiskReport] = None,
    risk_right: Optional[RiskReport] = None,
    facts_left: Optional[List] = None,
    facts_right: Optional[List] = None,
    label_left: str = "Document A",
    label_right: str = "Document B",
) -> str:
    """Render a complete, self-contained HTML diff report.

    Mirrors ``render_markdown``: same sections, same data, all escaped.
    """
    meta = [
        f'<p class="docmeta"><b>Document A:</b> {_h(report.document_left or "(unnamed)")}</p>',
        f'<p class="docmeta"><b>Document B:</b> {_h(report.document_right or "(unnamed)")}</p>',
        '<p class="docmeta"><b>Engine:</b> local paragraph-level diff '
        "(difflib / Myers-style), LLM-free</p>",
    ]
    if risk_left is not None and risk_right is not None:
        meta.append(
            f'<p class="riskline">Overall risk: A {risk_left.overall_score}/100 vs '
            f"B {risk_right.overall_score}/100 &mdash; changed clauses are annotated "
            "with the penalties that fired on them.</p>"
        )

    body = ["<div class=\"wrap\">", "<h1>Contract Clause Diff Report</h1>"]
    body.extend(meta)
    body.append(f'<h2>Summary</h2><p class="summary">{_h(report.summary)}</p>')

    if facts_left is not None and facts_right is not None:
        left_table = _facts_table(facts_left)
        right_table = _facts_table(facts_right)
        if left_table or right_table:
            body.append("<h2>Contract key facts</h2>")
            body.append(f"<h3>{_h(label_left or 'Document A')}</h3>")
            body.append(left_table or '<p class="note">No key fields detected.</p>')
            body.append(f"<h3>{_h(label_right or 'Document B')}</h3>")
            body.append(right_table or '<p class="note">No key fields detected.</p>')

    if risk_left is not None and risk_right is not None:
        body.append("<h2>Risk by dimension</h2>")
        body.append(_dimensions_table(risk_left, label_left or "Document A"))
        body.append(_dimensions_table(risk_right, label_right or "Document B"))

    left_map = _risk_by_para(risk_left) if risk_left is not None else {}
    right_map = _risk_by_para(risk_right) if risk_right is not None else {}
    has_risk = risk_left is not None or risk_right is not None

    sections = [(n.label, n.items) for n in report.root.children if n.items]
    for label, items in sections:
        body.append(f'<h2 class="section">{_h(label)}</h2>')
        for it in items:
            note = ""
            if has_risk:
                note = _risk_note(it, left_map, right_map, label_left, label_right)
            body.append(_bullet(it) + note + "</div>")

    if has_risk:
        top = _top_risky_clauses(sections, left_map, right_map, n=5)
        if top:
            body.append("<h2>Highest-risk clauses</h2>")
            body.append(
                '<p class="note">The changed clauses that accumulated the most '
                "risk points (A + B combined), ranked &mdash; review these first.</p>"
            )
            for label, it, total in top:
                body.append('<div class="ranked">')
                body.append(
                    f"<h4>{_h(it.summary[:90])}</h4>"
                    f'<p><code>{_h(label)}</code> &middot; {total} risk pts</p>'
                )
                note = _risk_note(it, left_map, right_map, label_left, label_right)
                if note:
                    body.append(note)
                body.append("</div>")

    if has_risk:
        by_section = _risk_by_section(sections, left_map, right_map)
        if by_section:
            body.append("<h2>Risk by section</h2>")
            body.append(
                '<p class="note">Where the changed-clause risk points '
                "concentrate &mdash; combined A + B severity.</p>"
            )
            rows = ["<table><thead><tr><th>Section</th><th>Left (A)</th>"
                    "<th>Right (B)</th><th>Total</th></tr></thead><tbody>"]
            for label, left_pts, right_pts, total in by_section:
                rows.append(
                    f"<tr><td><code>{_h(label[:50])}</code></td>"
                    f"<td>{left_pts}</td><td>{right_pts}</td><td>{total}</td></tr>"
                )
            rows.append("</tbody></table>")
            body.append("".join(rows))

    body.append("<h2>Change ledger</h2>")
    rows = ["<table><thead><tr><th>#</th><th>Op</th><th>Section</th>"
            "<th>Left&para;</th><th>Right&para;</th><th>Risk</th></tr></thead><tbody>"]
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
                risk_cell = " &middot; ".join(cell_parts) if cell_parts else "—"
            else:
                risk_cell = "—"
            rows.append(
                f"<tr><td>{n}</td><td>{op}</td><td><code>{_h(label[:40])}</code></td>"
                f"<td>{lp}</td><td>{rp}</td><td>{_h(risk_cell)}</td></tr>"
            )
    rows.append("</tbody></table>")
    body.append("".join(rows))

    body.append(
        '<p class="footer">Generated by LawRisk diff engine &mdash; '
        f"{report.stats.additions} additions, {report.stats.deletions} deletions, "
        f"{report.stats.modifications} modifications.</p>"
    )
    body.append("</div>")

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Contract Clause Diff Report</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>"
    )
