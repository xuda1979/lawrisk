"""FastAPI application: upload two docs -> diff tree + risk panel.

Design:
  POST /api/compare  (multipart) two files: template_a, template_b
      -> CompareResult { diff: DiffReport, risk_a, risk_b, rows, markdown }
  GET  /api/health
  POST /api/parse     single file -> parsed paragraphs + fields (debug)
  POST /api/score     JSON {paragraphs: [...]} -> RiskReport
  POST /api/diff-text JSON {left, right, name_left, name_right} -> CompareResult
  GET  /api/templates         -> bundled clause-template library (P3)
  POST /api/templates/{tid}/compare  one file -> diff doc vs template + risk

All endpoints are local and deterministic; LLM summarisation is optional
(off by default). Uploaded files are size-limited (413) to keep memory bounded.
"""

from __future__ import annotations

import base64
import uuid
from typing import Dict, List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from lawrisk.diff.differ import build_diff_tree, diff_texts
from lawrisk.diff.docx_report import render_docx
from lawrisk.diff.html_report import render_html
from lawrisk.diff.markdown_report import render_markdown
from lawrisk.diff.sidebyside import aligned_rows, to_dict
from lawrisk.diff.single_report import (
    render_docx_review,
    render_html_review,
    render_markdown_review,
)
from lawrisk.fields import extract_fields
from lawrisk.textutil import split_paragraphs
from lawrisk.llm import describe_layer, summarize_clause
from lawrisk.models import DocParse, RiskReport
from lawrisk.parser import parse_document
from lawrisk.rules import ENGINE_VERSION, rule_catalog, score_document
from lawrisk.static import mount_spa_if_available
from lawrisk.templates import diff_against_template, get_template, list_templates

app = FastAPI(
    title="LawRisk",
    description="Law-firm contract risk scoring + clause diff tree",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local SPA
    allow_methods=["*"],
    allow_headers=["*"],
)

# Hard cap on any single uploaded file (keeps parsing memory-bounded).
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class ScoreRequest(BaseModel):
    paragraphs: List[str]


class DiffTextRequest(BaseModel):
    left: str
    right: str
    name_left: str = "left"
    name_right: str = "right"


class CompareResult(BaseModel):
    diff: object
    risk_a: RiskReport
    risk_b: RiskReport
    rows: list
    markdown: str
    llm_enabled: bool
    facts_a: list = Field(default_factory=list, description="Extracted key fields (A side)")
    facts_b: list = Field(default_factory=list, description="Extracted key fields (B side)")
    report_docx: str = Field(default="", description="Base64 .docx diff report")
    report_html: str = Field(default="", description="Self-contained HTML diff report")


class ParseResult(BaseModel):
    doc: DocParse
    llm_enabled: bool


class ReviewResult(BaseModel):
    """Single-document risk review: score + section-grouped findings + reports."""

    document_name: str
    risk: RiskReport
    facts: list = Field(default_factory=list, description="Extracted key fields")
    sections: list = Field(
        default_factory=list,
        description="Findings grouped by contract section: [{heading, total_risk, findings}]",
    )
    markdown: str = Field(default="", description="Markdown review report")
    report_docx: str = Field(default="", description="Base64 .docx review report")
    report_html: str = Field(default="", description="Self-contained HTML review report")
    llm_enabled: bool = False


class TemplateListResult(BaseModel):
    templates: list
    llm: dict


class RuleCatalogResult(BaseModel):
    engine: str = Field(default=ENGINE_VERSION, description="Risk engine version string")
    source: str = Field(
        default="lawrisk.rules", description="Python module the catalog is generated from"
    )
    rules: list = Field(
        default_factory=list,
        description="Full rule catalog: {rule_id, dimension, severity, reason, mitigation, kind, ...}",
    )


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_enabled": describe_layer()["enabled"],
        "engine": "lawrisk-engine-v1",
        "llm": describe_layer(),
    }


async def _read_limited(file: UploadFile) -> bytes:
    """Read an upload, rejecting anything over the hard size cap."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{file.filename or 'file'} exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB upload limit",
        )
    return data


@app.post("/api/parse", response_model=ParseResult)
async def parse_file(file: UploadFile = File(...)) -> ParseResult:
    data = await _read_limited(file)
    try:
        dp = parse_document(data, uuid.uuid4().hex[:8], file.filename or "")
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=422, detail=f"could not parse {file.filename}: {exc}")
    return ParseResult(doc=dp, llm_enabled=describe_layer()["enabled"])


@app.post("/api/score", response_model=RiskReport)
def score_paragraphs(req: ScoreRequest) -> RiskReport:
    if not req.paragraphs:
        raise HTTPException(status_code=422, detail="paragraphs must be non-empty")
    # Bound the request: 5k paragraphs / 1 MiB of text is far beyond legal docs.
    if len(req.paragraphs) > 5000:
        raise HTTPException(status_code=413, detail="too many paragraphs")
    if sum(len(p) for p in req.paragraphs) > 1_000_000:
        raise HTTPException(status_code=413, detail="request text too large")
    return score_document(req.paragraphs, document_id=uuid.uuid4().hex[:8])


def _risk_panel(name: str, paragraphs: List[str]) -> RiskReport:
    return score_document(paragraphs, document_id=f"{name}-{uuid.uuid4().hex[:8]}")


def _risk_by_para(report: RiskReport) -> Dict[int, List[dict]]:
    """Map global paragraph index -> penalties that fired on that paragraph."""
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


def _attach_row_risks(rows: List[dict], risk_a: RiskReport, risk_b: RiskReport) -> List[dict]:
    """Attribute risk penalties to diff rows.

    Diff rows and the risk engine index the same global paragraph arrays, so a
    penalty's para_index tells us exactly which changed clause carried the
    points. Each row gains per-side lists (leftRisks/rightRisks) plus the
    summed severity so the web diff can flag risky changed clauses.
    """
    left_map = _risk_by_para(risk_a)
    right_map = _risk_by_para(risk_b)
    for r in rows:
        lk = r.get("leftIdx")
        rk = r.get("rightIdx")
        left = left_map.get(lk, []) if lk is not None else []
        right = right_map.get(rk, []) if rk is not None else []
        r["leftRisks"] = left
        r["rightRisks"] = right
        r["leftRiskSum"] = sum(p["severity"] for p in left)
        r["rightRiskSum"] = sum(p["severity"] for p in right)
    return rows


@app.post("/api/diff-text", response_model=CompareResult)
def diff_text(req: DiffTextRequest) -> CompareResult:
    if not req.left.strip() or not req.right.strip():
        raise HTTPException(status_code=422, detail="left/right must be non-empty")
    report = diff_texts(req.left, req.right, req.name_left, req.name_right)
    report = _maybe_llm_summaries(report)
    paras_a = list(split_paragraphs(req.left))
    paras_b = list(split_paragraphs(req.right))
    risk_a = _risk_panel(req.name_left, paras_a)
    risk_b = _risk_panel(req.name_right, paras_b)
    rows = _attach_row_risks([to_dict(r) for r in aligned_rows(report)], risk_a, risk_b)
    return CompareResult(
        diff=report.model_dump(),
        risk_a=risk_a,
        risk_b=risk_b,
        rows=rows,
        markdown=render_markdown(
            report, risk_left=risk_a, risk_right=risk_b,
            facts_left=[f.model_dump() for f in extract_fields(paras_a, req.left)],
            facts_right=[f.model_dump() for f in extract_fields(paras_b, req.right)],
            label_left=req.name_left, label_right=req.name_right,
        ),
        report_docx=base64.b64encode(render_docx(
            report, risk_left=risk_a, risk_right=risk_b,
            facts_left=[f.model_dump() for f in extract_fields(paras_a, req.left)],
            facts_right=[f.model_dump() for f in extract_fields(paras_b, req.right)],
            label_left=req.name_left, label_right=req.name_right,
        )).decode("ascii"),
        report_html=render_html(
            report, risk_left=risk_a, risk_right=risk_b,
            facts_left=[f.model_dump() for f in extract_fields(paras_a, req.left)],
            facts_right=[f.model_dump() for f in extract_fields(paras_b, req.right)],
            label_left=req.name_left, label_right=req.name_right,
        ),
        llm_enabled=describe_layer()["enabled"],
        facts_a=[f.model_dump() for f in extract_fields(paras_a, req.left)],
        facts_b=[f.model_dump() for f in extract_fields(paras_b, req.right)],
    )


@app.post("/api/compare", response_model=CompareResult)
async def compare(
    template_a: UploadFile = File(...),
    template_b: UploadFile = File(...),
    name_a: str = Form(default="Template A"),
    name_b: str = Form(default="Template B"),
) -> CompareResult:
    """Compare two uploaded documents: diff tree + risk panels."""
    data_a = await _read_limited(template_a)
    data_b = await _read_limited(template_b)
    try:
        doc_a = parse_document(data_a, uuid.uuid4().hex[:8], template_a.filename or "")
        doc_b = parse_document(data_b, uuid.uuid4().hex[:8], template_b.filename or "")
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=422, detail=f"parse failed: {exc}")

    if not doc_a.paragraphs or not doc_b.paragraphs:
        raise HTTPException(status_code=422, detail="both documents must yield paragraphs")

    report = build_diff_tree(doc_a.paragraphs, doc_b.paragraphs, name_a, name_b)
    risk_a = score_document(doc_a.paragraphs, doc_a.document_id)
    risk_b = score_document(doc_b.paragraphs, doc_b.document_id)
    report = _maybe_llm_summaries(report)

    rows = _attach_row_risks([to_dict(r) for r in aligned_rows(report)], risk_a, risk_b)
    return CompareResult(
        diff=report.model_dump(),
        risk_a=risk_a,
        risk_b=risk_b,
        rows=rows,
        markdown=render_markdown(
            report, risk_left=risk_a, risk_right=risk_b,
            facts_left=[f.model_dump() for f in doc_a.fields],
            facts_right=[f.model_dump() for f in doc_b.fields],
            label_left=name_a, label_right=name_b,
        ),
        report_docx=base64.b64encode(render_docx(
            report, risk_left=risk_a, risk_right=risk_b,
            facts_left=[f.model_dump() for f in doc_a.fields],
            facts_right=[f.model_dump() for f in doc_b.fields],
            label_left=name_a, label_right=name_b,
        )).decode("ascii"),
        report_html=render_html(
            report, risk_left=risk_a, risk_right=risk_b,
            facts_left=[f.model_dump() for f in doc_a.fields],
            facts_right=[f.model_dump() for f in doc_b.fields],
            label_left=name_a, label_right=name_b,
        ),
        llm_enabled=describe_layer()["enabled"],
        facts_a=[f.model_dump() for f in doc_a.fields],
        facts_b=[f.model_dump() for f in doc_b.fields],
    )


@app.get("/api/templates", response_model=TemplateListResult)
def template_library() -> TemplateListResult:
    """List the bundled clause-template library (P3)."""
    return TemplateListResult(
        templates=[t.to_dict() for t in list_templates()],
        llm=describe_layer(),
    )


@app.get("/api/rules", response_model=RuleCatalogResult)
def rules_catalog() -> RuleCatalogResult:
    """Return the full, deterministic risk rule catalog (handbook)."""
    return RuleCatalogResult(engine=ENGINE_VERSION, rules=rule_catalog())


@app.post("/api/templates/{template_id}/compare", response_model=CompareResult)
async def compare_template(
    template_id: str,
    document: UploadFile = File(...),
    name: str = Form(default="Document"),
) -> CompareResult:
    """Diff an uploaded document against a bundled baseline template."""
    data = await _read_limited(document)
    try:
        doc = parse_document(data, uuid.uuid4().hex[:8], document.filename or "")
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=422, detail=f"parse failed: {exc}")
    if not doc.paragraphs:
        raise HTTPException(status_code=422, detail="document must yield paragraphs")

    try:
        report = diff_against_template(doc.paragraphs, template_id, document_name=name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown template: {template_id}")

    report = _maybe_llm_summaries(report)
    risk = score_document(doc.paragraphs, doc.document_id)
    # Real risk panel for the baseline template itself so both sides of the
    # comparison are scored and explainable (baselines are curated low-risk).
    tpl = get_template(template_id)
    baseline_paragraphs = (
        split_paragraphs("\n\n".join(tpl.paragraphs)) if tpl else []
    )
    baseline_risk = score_document(
        baseline_paragraphs, document_id=f"template:{template_id}"
    )
    baseline_full = "\n\n".join(baseline_paragraphs)
    doc_full = "\n\n".join(doc.paragraphs)
    rows = _attach_row_risks([to_dict(r) for r in aligned_rows(report)], baseline_risk, risk)
    return CompareResult(
        diff=report.model_dump(),
        risk_a=baseline_risk,
        risk_b=risk,
        rows=rows,
        markdown=render_markdown(
            report, risk_left=baseline_risk, risk_right=risk,
            facts_left=[f.model_dump() for f in extract_fields(baseline_paragraphs, baseline_full)],
            facts_right=[f.model_dump() for f in doc.fields],
            label_left="Template", label_right=name,
        ),
        report_docx=base64.b64encode(render_docx(
            report, risk_left=baseline_risk, risk_right=risk,
            facts_left=[f.model_dump() for f in extract_fields(baseline_paragraphs, baseline_full)],
            facts_right=[f.model_dump() for f in doc.fields],
            label_left="Template", label_right=name,
        )).decode("ascii"),
        report_html=render_html(
            report, risk_left=baseline_risk, risk_right=risk,
            facts_left=[f.model_dump() for f in extract_fields(baseline_paragraphs, baseline_full)],
            facts_right=[f.model_dump() for f in doc.fields],
            label_left="Template", label_right=name,
        ),
        llm_enabled=describe_layer()["enabled"],
        facts_a=[f.model_dump() for f in extract_fields(baseline_paragraphs, baseline_full)],
        facts_b=[f.model_dump() for f in doc.fields],
    )


@app.post("/api/review", response_model=ReviewResult)
async def review_document(
    file: UploadFile = File(...),
    name: str = Form(default="Document"),
) -> ReviewResult:
    """Score a single uploaded document and group findings by contract section."""
    data = await _read_limited(file)
    try:
        doc = parse_document(data, uuid.uuid4().hex[:8], file.filename or "")
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=422, detail=f"could not parse {file.filename}: {exc}")
    if not doc.paragraphs:
        raise HTTPException(status_code=422, detail="document must yield paragraphs")

    risk = score_document(doc.paragraphs, doc.document_id)
    facts = [f.model_dump() for f in doc.fields]
    return ReviewResult(
        document_name=name,
        risk=risk,
        facts=facts,
        sections=_review_sections(doc.paragraphs, risk),
        markdown=render_markdown_review(name, doc.paragraphs, risk, facts),
        report_docx=base64.b64encode(
            render_docx_review(name, doc.paragraphs, risk, facts)
        ).decode("ascii"),
        report_html=render_html_review(name, doc.paragraphs, risk, facts),
        llm_enabled=describe_layer()["enabled"],
    )


def _review_sections(paragraphs: List[str], report: RiskReport) -> List[dict]:
    """Group fired penalties under the contract section they fall in (for JSON)."""
    from lawrisk.diff.single_report import _group_by_section

    return _group_by_section(paragraphs, report)


def _maybe_llm_summaries(report):
    if describe_layer()["enabled"]:
        for node in report.root.children:
            for it in node.items:
                it.summary = summarize_clause(it.text_left, it.text_right, it.op.value)
    return report


# Single-port production serving: when a built frontend exists, serve it from
# the same process. Registered last so the SPA catch-all never shadows /api.
mount_spa_if_available(app)
