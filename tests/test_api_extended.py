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
