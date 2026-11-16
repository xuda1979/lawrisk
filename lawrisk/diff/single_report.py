"""Single-document risk review reports (Markdown / .docx / HTML).

Every other flow (compare, diff-text, template-compare) needs two documents.
The core SPEC workflow is a lawyer reviewing ONE contract: score a single
document with the deterministic risk engine and render the findings grouped by
contract section, so you can see at a glance which parts of the agreement
concentrate the risk.

The three renderers mirror each other section-for-section:

  * Document name + overall risk score/level header
  * Contract key facts (currency / term / governing law / arbitration)
  * Risk by dimension (per-dimension score, level, finding count)
  * Per-section finding lists — each finding shows the rule id, severity,
    dimension, the readable reason, the verbatim source paragraph and any
    mitigation
  * A severity-ranked "highest-risk clauses" shortlist and a per-section
    risk-triage table

All three reuse the shared helpers from the diff report modules so the
output stays visually consistent with the two-document reports. As with the
HTML diff report, every document byte passes through an HTML escaper so raw
markup in the contract can never execute in the rendered page.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Sequence

from lawrisk.diff.differ import split_sections
from lawrisk.diff.html_report import _CSS, _h, _facts_table as _facts_table_html
from lawrisk.diff.markdown_report import (
    DIM_LABEL,
    _dimensions_table as _dimensions_table_md,
    _facts_table as _facts_table_md,
)

_PREAMBLE_LABEL = "Preamble"
_FALLBACK_LABEL = "Preamble / unlocated"


def _penalties_by_para(risk) -> Dict[int, List[dict]]:
    """Map global paragraph indices to their fired penalties (skips None)."""
    out: Dict[int, List[dict]] = {}
    for p in risk.penalties:
        if p.para_index is None:
            continue
        out.setdefault(p.para_index, []).append(
            {
                "rule_id": p.rule_id,
                "dimension": getattr(p.dimension, "value", str(p.dimension)),
                "severity": p.severity,
                "reason": p.reason,
                "excerpt": p.excerpt,
                "mitigation": p.mitigation,
            }
        )
    return out


def _group_by_section(paragraphs: Sequence[str], risk) -> List[dict]:
    """Group fired penalties under the contract section they fall in.

    Reuses the diff engine's ``split_sections`` so the grouping matches the
    sectioning the diff tree uses. A penalty belongs to a section when its
    ``para_index`` satisfies ``sec.start <= para_index < next.start``; sections
    are compared by their display heading ("" -> "Preamble"); penalties with no
    paragraph index land in a fallback bucket. Sections with no findings are
    omitted. Returns ``[{heading, total_risk, findings: [...] }]``.
    """
    sections = split_sections(paragraphs)
    by_para = _penalties_by_para(risk)

    buckets: List[Dict[str, object]] = []
    for i, sec in enumerate(sections):
        # upper bound = next section's start, or one-past-the-last-para
        upper_bound = sections[i + 1].start if i + 1 < len(sections) else len(paragraphs)
        findings = []
        for para_index in range(sec.start, upper_bound):
            findings.extend(by_para.get(para_index, []))
        # only keep sections that actually carry findings
        if not findings:
            continue
        heading = sec.heading or _PREAMBLE_LABEL
        total = sum(f["severity"] for f in findings)
        buckets.append(
            {
                "heading": heading,
                "total_risk": total,
                "findings": findings,
            }
        )

    # Penalties whose para_index is None (document-level rules) get a bucket of
    # their own so they are never silently dropped from the review.
    unlocated = [p for p in risk.penalties if p.para_index is None]
    if unlocated:
        rows = []
        for p in unlocated:
            rows.append(
                {
                    "rule_id": p.rule_id,
                    "dimension": getattr(p.dimension, "value", str(p.dimension)),
                    "severity": p.severity,
                    "reason": p.reason,
                    "excerpt": p.excerpt,
                    "mitigation": p.mitigation,
                }
            )
        buckets.append(
            {
                "heading": _FALLBACK_LABEL,
                "total_risk": sum(p.severity for p in unlocated),
                "findings": rows,
            }
        )

    return buckets


def _ranked_findings(buckets: List[dict], n: int = 5) -> List[tuple]:
    """Top-n individual findings by severity (heading, finding) for triage."""
    ranked = []
    for bucket in buckets:
        for f in bucket["findings"]:
            ranked.append((bucket["heading"], f, f["severity"]))
    ranked.sort(key=lambda t: t[2], reverse=True)
    return ranked[:n]


def render_markdown_review(
    name: str, paragraphs: Sequence[str], risk, facts: List[Mapping]
) -> str:
    """Render a single-document risk review as a self-contained Markdown report."""
    buckets = _group_by_section(paragraphs, risk)
    lines: List[str] = []
    lines.append("# Contract Risk Review")
    lines.append("")
    lines.append(f"- **Document:** {name or '(unnamed)'}")
    lines.append("- **Engine:** deterministic rule-based scoring (LLM-free)")
    lines.append(
        f"- **Overall risk:** {risk.overall_score}/100 ({risk.overall_level.value})"
    )
    lines.append("")
    lines.append(f"## Summary")
    lines.append("")
    lines.append(risk.summary)
    lines.append("")

    facts_table = _facts_table_md(facts)
    if facts_table:
        lines.append("## Contract key facts")
        lines.append("")
        lines.append(facts_table)
        lines.append("")

    lines.append("## Risk by dimension")
    lines.append("")
    lines.append(_dimensions_table_md(risk, name or "Document"))
    lines.append("")

    if not buckets and not risk.penalties:
        lines.append("## Findings")
        lines.append("")
        lines.append("_No risk findings — this document scored clean._")
        lines.append("")
        return "\n".join(lines)

    for bucket in buckets:
        heading = bucket["heading"]
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(
            f"{len(bucket['findings'])} finding"
            f"{'' if len(bucket['findings']) == 1 else 's'} · "
            f"{bucket['total_risk']} risk pts"
        )
        lines.append("")
        for f in bucket["findings"]:
            lines.append(f"**{f['rule_id']}** (+{f['severity']}, {f['dimension']}): {f['reason']}")
            if f.get("mitigation"):
                lines.append(f"  - Fix: {f['mitigation']}")
            if f.get("excerpt"):
                excerpt = (f["excerpt"] or "").replace("\n", " ").strip()
                if excerpt:
                    lines.append(f"  - Source: “{excerpt[:220]}”")
            lines.append("")

    top = _ranked_findings(buckets, n=5)
    if top:
        lines.append("## Highest-risk findings")
        lines.append("")
        lines.append("The individual findings that carry the most points — review these first.")
        lines.append("")
        for heading, f, severity in top:
            lines.append(f"**{f['rule_id']}** (+{severity}, {f['dimension']}): {f['reason']}")
            lines.append("")
            lines.append(f"`{heading[:60]}`")
            if f.get("excerpt"):
                excerpt = (f["excerpt"] or "").replace("\n", " ").strip()
                if excerpt:
                    lines.append(f"Source: “{excerpt[:180]}”")
            lines.append("")

    risk_sections = [
        (b["heading"], b["total_risk"], len(b["findings"])) for b in buckets
    ]
    risk_sections.sort(key=lambda t: t[1], reverse=True)
    if risk_sections:
        lines.append("## Risk by section")
        lines.append("")
        lines.append("Where the findings concentrate — section-level severity.")
        lines.append("")
        lines.append("| Section | Risk pts | Findings |")
        lines.append("|---------|----------|----------|")
        for heading, total, count in risk_sections:
            lines.append(f"| `{heading[:50]}` | {total} | {count} |")
        lines.append("")

    lines.append("---")
    lines.append(
        f"_Generated by LawRisk risk engine — deterministic hash "
        f"{risk.deterministic_hash[:12]}._"
    )
    return "\n".join(lines)


def render_docx_review(
    name: str, paragraphs: Sequence[str], risk, facts: List[Mapping]
) -> bytes:
    """Render the single-document review as a .docx document (raw bytes)."""
    from io import BytesIO

    from docx import Document
    from docx.shared import Inches, RGBColor

    from lawrisk.diff.docx_report import (
        _facts_rows,
        _write_facts_table,
    )

    AMBER = RGBColor(0xB8, 0x86, 0x0B)
    GREY = RGBColor(0x55, 0x55, 0x55)

    buckets = _group_by_section(paragraphs, risk)
    doc = Document()

    doc.add_heading("Contract Risk Review", level=0)
    doc.add_paragraph(f"Document: {name or '(unnamed)'}")
    doc.add_paragraph("Engine: deterministic rule-based scoring (LLM-free)")
    p = doc.add_paragraph()
    p.add_run("Overall risk: ").bold = True
    p.add_run(f"{risk.overall_score}/100 ({risk.overall_level.value})")

    doc.add_heading("Summary", level=2)
    doc.add_paragraph(risk.summary)

    facts_rows = _facts_rows(facts)
    if facts_rows:
        doc.add_heading("Contract key facts", level=2)
        _write_facts_table(doc, facts_rows)

    doc.add_heading("Risk by dimension", level=2)
    _dimensions_table(doc, risk, name or "Document")

    if not buckets and not risk.penalties:
        doc.add_heading("Findings", level=2)
        doc.add_paragraph("No risk findings — this document scored clean.").italic = True

    for bucket in buckets:
        heading = bucket["heading"]
        doc.add_heading(heading, level=2)
        sub = doc.add_paragraph()
        sub_run = sub.add_run(
            f"{len(bucket['findings'])} finding"
            f"{'' if len(bucket['findings']) == 1 else 's'} · "
            f"{bucket['total_risk']} risk pts"
        )
        sub_run.italic = True
        for f in bucket["findings"]:
            pf = doc.add_paragraph(style="List Bullet")
            run = pf.add_run(f"{f['rule_id']} (+{f['severity']}, {f['dimension']}): {f['reason']}")
            if f.get("mitigation"):
                run.add_break()
                run.add_text(f"Fix: {f['mitigation']}")
            if f.get("excerpt"):
                excerpt = (f["excerpt"] or "").replace("\n", " ").strip()
                if excerpt:
                    ep = doc.add_paragraph()
                    ep.paragraph_format.left_indent = Inches(0.4)
                    ep.add_run(f"Source: “{excerpt[:220]}”").italic = True

    top = _ranked_findings(buckets, n=5)
    if top:
        doc.add_heading("Highest-risk findings", level=2)
        intro = doc.add_paragraph()
        intro_run = intro.add_run(
            "The individual findings that carry the most points — review these first."
        )
        intro_run.italic = True
        for heading, f, severity in top:
            pf = doc.add_paragraph(style="List Bullet")
            pf.add_run(f"{f['rule_id']} (+{severity}, {f['dimension']}): {f['reason']}  ").bold = True
            pf.add_run(f"· {heading[:60]}")
            if f.get("excerpt"):
                excerpt = (f["excerpt"] or "").replace("\n", " ").strip()
                if excerpt:
                    ep = doc.add_paragraph()
                    ep.paragraph_format.left_indent = Inches(0.4)
                    ep.add_run(f"Source: “{excerpt[:180]}”").italic = True

    risk_sections = [
        (b["heading"], b["total_risk"], len(b["findings"])) for b in buckets
    ]
    risk_sections.sort(key=lambda t: t[1], reverse=True)
    if risk_sections:
        doc.add_heading("Risk by section", level=2)
        intro = doc.add_paragraph()
        intro_run = intro.add_run("Where the findings concentrate — section-level severity.")
        intro_run.italic = True
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        for i, h in enumerate(("Section", "Risk pts", "Findings")):
            table.rows[0].cells[i].text = h
        for heading, total, count in risk_sections:
            cells = table.add_row().cells
            cells[0].text = heading[:50]
            cells[1].text = str(total)
            cells[2].text = str(count)

    footnote = doc.add_paragraph()
    run = footnote.add_run(
        f"Generated by LawRisk risk engine — deterministic hash {risk.deterministic_hash[:12]}."
    )
    run.italic = True
    run.font.color.rgb = GREY

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render_html_review(
    name: str, paragraphs: Sequence[str], risk, facts: List[Mapping]
) -> str:
    """Render the single-document review as a standalone, self-contained HTML doc."""
    buckets = _group_by_section(paragraphs, risk)

    meta = [
        f'<p class="docmeta"><b>Document:</b> {_h(name or "(unnamed)")}</p>',
        '<p class="docmeta"><b>Engine:</b> deterministic rule-based scoring (LLM-free)</p>',
        f'<p class="riskline">Overall risk: {risk.overall_score}/100 '
        f"({_h(risk.overall_level.value)})</p>",
    ]

    body = ['<div class="wrap">', "<h1>Contract Risk Review</h1>"]
    body.extend(meta)
    body.append(f'<h2>Summary</h2><p class="summary">{_h(risk.summary)}</p>')

    facts_table = _facts_table_html(facts)
    if facts_table:
        body.append("<h2>Contract key facts</h2>")
        body.append(facts_table)

    body.append("<h2>Risk by dimension</h2>")
    body.append(_dimensions_table_html_review(risk, name or "Document"))

    if not buckets and not risk.penalties:
        body.append('<h2>Findings</h2><p class="note">No risk findings — '
                    "this document scored clean.</p>")

    for bucket in buckets:
        heading = bucket["heading"]
        body.append(f'<h2 class="section">{_h(heading)}</h2>')
        body.append(
            f'<p class="note">{len(bucket["findings"])} finding'
            f"{'' if len(bucket['findings']) == 1 else 's'} &middot; "
            f"{bucket['total_risk']} risk pts</p>"
        )
        for f in bucket["findings"]:
            parts = [
                f'<span class="pill mod">{_h(f["rule_id"])}</span> '
                f'<b>+{f["severity"]}, {_h(f["dimension"])}</b> &mdash; {_h(f["reason"])}'
            ]
            if f.get("mitigation"):
                parts.append(f'<p class="clause-detail">Fix: {_h(f["mitigation"])}</p>')
            if f.get("excerpt"):
                excerpt = (f["excerpt"] or "").replace("\n", " ").strip()
                if excerpt:
                    parts.append(
                        '<p class="excerpt">&ldquo;{0}&rdquo;</p>'.format(
                            _h(excerpt[:220])
                        )
                    )
            body.append('<div class="clause">' + "".join(parts) + "</div>")

    top = _ranked_findings(buckets, n=5)
    if top:
        body.append("<h2>Highest-risk findings</h2>")
        body.append(
            '<p class="note">The individual findings that carry the most points '
            "&mdash; review these first.</p>"
        )
        for heading, f, severity in top:
            parts = [
                f'<h4><span class="pill mod">{_h(f["rule_id"])}</span> '
                f'+{severity}, {_h(f["dimension"])} &mdash; {_h(f["reason"])}</h4>',
                f'<p><code>{_h(heading[:60])}</code></p>',
            ]
            if f.get("excerpt"):
                excerpt = (f["excerpt"] or "").replace("\n", " ").strip()
                if excerpt:
                    parts.append(
                        '<p class="excerpt">&ldquo;{0}&rdquo;</p>'.format(
                            _h(excerpt[:180])
                        )
                    )
            body.append('<div class="ranked">' + "".join(parts) + "</div>")

    risk_sections = [
        (b["heading"], b["total_risk"], len(b["findings"])) for b in buckets
    ]
    risk_sections.sort(key=lambda t: t[1], reverse=True)
    if risk_sections:
        body.append("<h2>Risk by section</h2>")
        body.append(
            '<p class="note">Where the findings concentrate &mdash; '
            "section-level severity.</p>"
        )
        rows = ["<table><thead><tr><th>Section</th><th>Risk pts</th>"
                "<th>Findings</th></tr></thead><tbody>"]
        for heading, total, count in risk_sections:
            rows.append(
                f"<tr><td><code>{_h(heading[:50])}</code></td>"
                f"<td>{total}</td><td>{count}</td></tr>"
            )
        rows.append("</tbody></table>")
        body.append("".join(rows))

    body.append(
        '<p class="footer">Generated by LawRisk risk engine &mdash; deterministic '
        f"hash {_h(risk.deterministic_hash[:12])}.</p>"
    )
    body.append("</div>")

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Contract Risk Review</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>"
    )


def _dimensions_table_html_review(risk, label: str) -> str:
    """HTML per-dimension score table (mirrors the diff report's version)."""
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


def _dimensions_table(doc, risk, label: str) -> None:
    """docx per-dimension score table; local import keeps python-docx optional."""
    from lawrisk.diff.docx_report import _dimensions_table as _docx_dimensions

    _docx_dimensions(doc, risk, label)
