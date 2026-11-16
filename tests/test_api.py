"""P2: FastAPI integration tests (AC5 backend half)."""

from __future__ import annotations

from pathlib import Path

import httpx

from lawrisk.api import app

FIXTURES = Path(__file__).parent / "fixtures"


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health():
    from lawrisk.rules import ENGINE_VERSION

    async with _client() as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "llm_enabled" in body
    # The health endpoint must report the real engine version, not a copy.
    assert body["engine"] == ENGINE_VERSION


async def test_score_endpoint():
    async with _client() as c:
        r = await c.post(
            "/api/score", json={"paragraphs": ["auto-renew unless notice", "indemnify all claims"]}
        )
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["overall_score"] <= 100
    assert body["penalties"]


async def test_parse_endpoint():
    data = (FIXTURES / "template_a.docx").read_bytes()
    async with _client() as c:
        r = await c.post(
            "/api/parse",
            files={"file": ("template_a.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["doc"]["paragraphs"]
    assert "llm_enabled" in body


async def test_compare_endpoint_full_pipeline():
    a = (FIXTURES / "template_a.docx").read_bytes()
    b = (FIXTURES / "template_b.docx").read_bytes()
    async with _client() as c:
        r = await c.post(
            "/api/compare",
            files={
                "template_a": ("template_a.docx", a, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                "template_b": ("template_b.docx", b, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            },
            data={"name_a": "A", "name_b": "B"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["diff"]["stats"]["additions"] >= 0
    assert body["rows"]
    assert "risk_a" in body and "risk_b" in body
    assert body["markdown"].startswith("#")
    # The submitted names must surface as the compared documents' labels.
    assert body["diff"]["document_left"] == "A"
    assert body["diff"]["document_right"] == "B"


async def test_diff_text_endpoint():
    async with _client() as c:
        r = await c.post(
            "/api/diff-text",
            json={
                "left": "Term of 12 months; auto-renew.\nFees $1000.",
                "right": "Term of 24 months.\nFees $2000.",
                "name_left": "L",
                "name_right": "R",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["markdown"]
    assert body["rows"]


async def test_rules_catalog_endpoint():
    """AC6: the rule handbook serialises the full rule set (incl. absence rules)."""
    async with _client() as c:
        r = await c.get("/api/rules")
    assert r.status_code == 200
    body = r.json()
    assert body["engine"]
    entries = body["rules"]
    assert len(entries) >= 15
    assert len({e["rule_id"] for e in entries}) == len(entries)
    # Every dimension is covered by at least one paragraph rule.
    dims = {e["dimension"] for e in entries if e["kind"] == "paragraph"}
    assert {"commercial", "liability", "data", "export"} <= dims
    # Absence rules are included too.
    assert any(e["rule_id"] == "R-DATA-4" and e["kind"] == "absence" for e in entries)
    for e in entries:
        assert e["reason"]
        assert e["mitigation"]
        assert "severity" in e and e["severity"] > 0


async def test_rules_catalog_resolves_every_fired_penalty():
    """Invariant: any penalty id produced by scoring resolves in the catalog.

    This guarantees the handbook is always able to explain a finding the
    engine emits — the catalog can never drift from the rule set.
    """
    async with _client() as c:
        r = await c.get("/api/rules")
    catalog = {e["rule_id"] for e in r.json()["rules"]}
    # Score the riskiest fixture so a broad spread of rules actually fires.
    data = (FIXTURES / "risky_contract.docx").read_bytes()
    async with _client() as c:
        r = await c.post(
            "/api/parse",
            files={"file": ("risky_contract.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    paragraphs = r.json()["doc"]["paragraphs"]
    async with _client() as c:
        r = await c.post("/api/score", json={"paragraphs": paragraphs})
    fired = {p["rule_id"] for p in r.json()["penalties"]}
    assert fired, "risky_contract fixture must fire at least one rule"
    assert fired <= catalog, f"fired rules missing from catalog: {fired - catalog}"
