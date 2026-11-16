"""P2: FastAPI integration tests (AC5 backend half)."""

from __future__ import annotations

from pathlib import Path

import httpx

from lawrisk.api import app

FIXTURES = Path(__file__).parent / "fixtures"


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health():
    async with _client() as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "llm_enabled" in body


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
