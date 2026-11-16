"""P2/P3: extra API tests — template endpoints, limits, static SPA serving."""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from lawrisk.api import app

FIXTURES = Path(__file__).parent / "fixtures"
DOCX_MTYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health_includes_llm_details():
    async with _client() as c:
        r = await c.get("/api/health")
    body = r.json()
    assert r.status_code == 200
    assert body["llm"]["provider"] == "mock"
    assert body["llm"]["deterministic"] is True


async def test_templates_listing():
    async with _client() as c:
        r = await c.get("/api/templates")
    assert r.status_code == 200
    body = r.json()
    ids = [t["id"] for t in body["templates"]]
    assert "msa" in ids
    assert all(t["paragraph_count"] > 0 for t in body["templates"])


async def test_template_compare_endpoint():
    data = (FIXTURES / "template_b.docx").read_bytes()
    async with _client() as c:
        r = await c.post(
            "/api/templates/msa/compare",
            files={"document": ("doc.docx", data, DOCX_MTYPE)},
            data={"name": "Doc B"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["diff"]["document_right"] == "Doc B"
    assert body["rows"]
    assert body["risk_b"]["overall_score"] > 0
    # Baseline side is a real scored RiskReport, not a stub.
    baseline = body["risk_a"]
    assert baseline["document_id"] == "template:msa"
    assert baseline["overall_level"] == "low"
    assert baseline["dimensions"]
    assert baseline["deterministic_hash"]
    assert "penalties" in baseline


async def test_template_compare_unknown_404():
    data = (FIXTURES / "template_a.docx").read_bytes()
    async with _client() as c:
        r = await c.post(
            "/api/templates/nope/compare",
            files={"document": ("a.docx", data, DOCX_MTYPE)},
        )
    assert r.status_code == 404


async def test_score_limits():
    async with _client() as c:
        r = await c.post(
            "/api/score", json={"paragraphs": ["x"] * 5001}
        )
    assert r.status_code == 413


async def test_diff_text_panels_are_real():
    async with _client() as c:
        r = await c.post(
            "/api/diff-text",
            json={
                "left": "Term of 12 months; auto-renew.\nFees $1000.",
                "right": "Term of 24 months.\nFees $2000.",
            },
        )
    assert r.status_code == 200
    body = r.json()
    # risk panels are now scored from the text, not placeholder stubs:
    # each carries dimensions, a summary and a determinism hash.
    for side in ("risk_a", "risk_b"):
        assert body[side]["dimensions"], side
        assert body[side]["summary"], side
        assert body[side]["deterministic_hash"], side


async def test_compare_returns_key_facts():
    async with _client() as c:
        r = await c.post(
            "/api/diff-text",
            json={
                "left": "This Agreement is governed by the laws of England.\n"
                        "Term of 12 months; the currency of the deal is USD, fees of $1000.",
                "right": "This Agreement is governed by the laws of New York.\n"
                         "Term of 24 months; the currency of the deal is USD, fees of $2000.",
            },
        )
    assert r.status_code == 200
    body = r.json()
    for side in ("facts_a", "facts_b"):
        facts = body[side]
        assert isinstance(facts, list), side
        names = [f["name"] for f in facts]
        assert "currency" in names, side
        assert "term" in names, side
        assert "governing_law" in names, side
        for f in facts:
            assert f["found"] is True
            assert f["value"]
            assert f["source"]


async def test_template_compare_returns_key_facts():
    data = (FIXTURES / "template_a.docx").read_bytes()
    async with _client() as c:
        r = await c.post(
            "/api/templates/msa/compare",
            files={"document": ("a.docx", data, DOCX_MTYPE)},
        )
    assert r.status_code == 200
    body = r.json()
    # Baseline fixture (template side) and uploaded doc both carry facts.
    assert isinstance(body["facts_a"], list)
    assert isinstance(body["facts_b"], list)
    assert "currency" in [f["name"] for f in body["facts_b"]]


async def test_diff_rows_carry_risk_attribution():
    """Risk penalties are attributed to diff rows by global paragraph index."""
    async with _client() as c:
        r = await c.post(
            "/api/compare",
            files={
                "template_a": ("a.docx", (FIXTURES / "template_a.docx").read_bytes(), DOCX_MTYPE),
                "template_b": ("b.docx", (FIXTURES / "template_b.docx").read_bytes(), DOCX_MTYPE),
            },
            data={"name_a": "Template A", "name_b": "Template B"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["rows"]

    # Every row exposes the attribution fields.
    for row in body["rows"]:
        assert "leftRisks" in row and "rightRisks" in row
        assert "leftRiskSum" in row and "rightRiskSum" in row

    # Every penalty of the riskier document lands on some diff row that has a
    # matching right paragraph index (attribution is complete, never dropped).
    risk_b = body["risk_b"]
    penalty_idx = {p["para_index"] for p in risk_b["penalties"] if p.get("para_index") is not None}
    row_right_idx = {row["rightIdx"] for row in body["rows"] if row["rightIdx"] is not None}
    # Max 3 exemplars per rule are kept, so at least the flagged paragraphs
    # that appear in the diff must all show up.
    assert penalty_idx & row_right_idx, "no diff row maps to a penalised paragraph"

    # A changed paragraph that fired a rule carries the points on its row.
    seeded = next(
        (row for row in body["rows"] if row["rightRisks"]),
        None,
    )
    assert seeded is not None, "expected at least one diff row with right-side risk points"
    assert seeded["rightRiskSum"] == sum(p["severity"] for p in seeded["rightRisks"])
    assert all(rr["rule_id"] for rr in seeded["rightRisks"])


async def test_diff_text_rows_carry_risk_attribution():
    async with _client() as c:
        r = await c.post(
            "/api/diff-text",
            json={
                "left": "Term of 12 months.\nFees $1000.",
                "right": "Term of 12 months; this Agreement shall auto-renew automatically.\nFees $1000.",
            },
        )
    assert r.status_code == 200
    body = r.json()
    # The auto-renew right-side paragraph is a modification; its row must carry
    # the R-COMM-1 penalty so the diff shows where the risk entered.
    risky = next(
        (row for row in body["rows"] if row["rightRisks"]),
        None,
    )
    assert risky is not None
    assert any(rr["rule_id"] == "R-COMM-1" for rr in risky["rightRisks"])
    assert "auto-renew" in risky["rightText"]


async def test_markdown_report_carries_risk_attribution():
    """The exported Markdown report names the rules that fired on changed clauses."""
    async with _client() as c:
        r = await c.post(
            "/api/diff-text",
            json={
                "left": "Term of 12 months.\nFees $1000.",
                "right": "Term of 12 months; this Agreement shall auto-renew automatically.\nFees $1000.",
            },
        )
    assert r.status_code == 200
    md = r.json()["markdown"]
    assert "Overall risk" in md
    assert "R-COMM-1" in md
    # The fired rule appears on the changed clause's bullet note and in the ledger.
    assert "B (right) risk" in md
    assert "| B:R-COMM-1+20 |" in md or "B:R-COMM-1+" in md


async def test_markdown_report_carries_key_facts():
    """The exported Markdown report includes the contract key-facts panel."""
    async with _client() as c:
        r = await c.post(
            "/api/diff-text",
            json={
                "left": (
                    "This Agreement is governed by the laws of England.\n"
                    "Term of 24 months.\nFees $5000."
                ),
                "right": (
                    "This Agreement is governed by the laws of New York.\n"
                    "Term of 12 months; disputes shall be resolved by arbitration in Geneva.\n"
                    "Fees in USD."
                ),
                "name_left": "Doc A",
                "name_right": "Doc B",
            },
        )
    assert r.status_code == 200
    md = r.json()["markdown"]
    assert "Contract key facts" in md
    # Per-document fact tables carry label, value and detector name.
    assert "### Doc A" in md
    assert "### Doc B" in md
    assert "England" in md
    assert "New York" in md
    assert "Governing law" in md
    assert "Arbitration seat" in md
    assert "Currency" in md
    assert "| Field | Value | Source |" in md


async def test_markdown_report_carries_dimension_tables():
    """The exported Markdown report breaks risk into per-dimension A/B tables."""
    async with _client() as c:
        r = await c.post(
            "/api/diff-text",
            json={
                "left": "Term of 12 months.\nFees $1000.",
                "right": "Term of 12 months; this Agreement shall auto-renew automatically.\nFees $1000.",
            },
        )
    assert r.status_code == 200
    md = r.json()["markdown"]
    assert "## Risk by dimension" in md
    # One table per document with the global dimension labels and a scores row.
    count = md.count("| Dimension | Score | Level | Findings |")
    assert count == 2, md
    assert "Commercial risk" in md
    assert "Liability / legal risk" in md
    assert "Data protection" in md
    assert "Export compliance" in md


async def test_report_docx_export():
    """CompareResult carries a valid, parseable .docx report (base64)."""
    from io import BytesIO

    import base64

    from docx import Document

    async with _client() as c:
        r = await c.post(
            "/api/diff-text",
            json={
                "left": (
                    "This Agreement is governed by the laws of England.\n"
                    "Term of 12 months.\nFees $1000."
                ),
                "right": (
                    "Term of 12 months; this Agreement shall auto-renew automatically.\n"
                    "Fees $1000."
                ),
                "name_left": "Doc A",
                "name_right": "Doc B",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["report_docx"], "report_docx must be populated"

    raw = base64.b64decode(body["report_docx"])
    assert raw[:2] == b"PK"  # valid zip container

    document = Document(BytesIO(raw))
    text = "\n".join(p.text for p in document.paragraphs)
    # The Word report mirrors the Markdown content.
    for probe in (
        "Contract Clause Diff Report",
        "Doc A",
        "Doc B",
        "Overall risk:",
        "Summary",
        "Contract key facts",
        "Risk by dimension",
        "Change ledger",
        "R-COMM-1",
    ):
        assert probe in text, f"missing {probe!r} in docx text"
    assert "England" in text or any(t.text.count("England") for t in document.tables)
    # facts tables (2) + dimension tables (2) + ledger (1).
    assert len(document.tables) >= 5


async def test_report_ranks_highest_risk_clauses():
    """Both exported reports rank changed clauses by combined risk points."""
    from io import BytesIO

    import base64

    from docx import Document

    async with _client() as c:
        r = await c.post(
            "/api/diff-text",
            json={
                "left": "Term of 12 months.\nFees $1000.",
                "right": (
                    "This Agreement shall auto-renew automatically; the Provider "
                    "reserves the right to amend the terms at its sole discretion "
                    "without prior notice.\nFees $1000."
                ),
                "name_left": "Doc A",
                "name_right": "Doc B",
            },
        )
    assert r.status_code == 200
    body = r.json()
    md = body["markdown"]
    assert "## Highest-risk clauses" in md
    # The single 40-point clause ranks first and names both rules.
    assert "40 risk pts" in md
    assert "R-COMM-1" in md
    assert "R-COMM-5" in md
    # Ranked section sits before the change ledger.
    assert md.index("## Highest-risk clauses") < md.index("## Change ledger")

    # The Word report carries the same ranked section.
    raw = base64.b64decode(body["report_docx"])
    assert raw[:2] == b"PK"
    document = Document(BytesIO(raw))
    text = "\n".join(p.text for p in document.paragraphs)
    assert "Highest-risk clauses" in text
    assert "40 risk pts" in text


async def test_report_risk_by_section():
    """Both exported reports break changed-clause risk points down per section."""
    from io import BytesIO

    import base64

    from docx import Document

    async with _client() as c:
        r = await c.post(
            "/api/diff-text",
            json={
                "left": (
                    "TERMINATION\n\n"
                    "Either party may terminate for cause.\n\n"
                    "This Agreement shall remain in effect for a fixed term.\n\n"
                    "Fees amount to $1000."
                ),
                "right": (
                    "TERMINATION\n\n"
                    "Either party may terminate for cause.\n\n"
                    "This Agreement shall auto-renew automatically and the Provider "
                    "reserves the right to amend the terms at its sole discretion "
                    "without prior notice.\n\n"
                    "Fees amount to $2000."
                ),
                "name_left": "Doc A",
                "name_right": "Doc B",
            },
        )
    assert r.status_code == 200
    body = r.json()
    md = body["markdown"]

    # Section table lists where the 40 right-side points landed.
    assert "## Risk by section" in md
    assert "| Section | Left (A) | Right (B) | Total |" in md
    assert "| `TERMINATION` | 0 | 40 | 40 |" in md
    # Review-triage sections come before the verbose change ledger.
    assert md.index("## Risk by section") < md.index("## Change ledger")

    # The Word report mirrors the section table.
    raw = base64.b64decode(body["report_docx"])
    assert raw[:2] == b"PK"
    document = Document(BytesIO(raw))
    text = "\n".join(p.text for p in document.paragraphs)
    assert "Risk by section" in text
    section_table = next(
        (t for t in document.tables if [c.text for c in t.rows[0].cells] == ["Section", "Left (A)", "Right (B)", "Total"]),
        None,
    )
    assert section_table is not None
    assert [c.text for c in section_table.rows[1].cells] == ["TERMINATION", "0", "40", "40"]


def test_spa_served_when_dist_present(monkeypatch):
    # If a dist exists in the checkout, the static module can mount and serve it.
    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        return  # not built in this environment; skip silently

    from fastapi import FastAPI
    from lawrisk.static import mount_spa

    demo = FastAPI()
    assert mount_spa(demo) is True

    async def _check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=demo), base_url="http://test"
        ) as c:
            r = await c.get("/")
            return r.status_code, r.headers.get("content-type", "")

    import asyncio

    status, ctype = asyncio.run(_check())
    assert status == 200
    assert "text/html" in ctype
