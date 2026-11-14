"""Pydantic schemas shared across the LawRisk engine and API."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Dimension(str, Enum):
    COMMERCIAL = "commercial"
    LIABILITY = "liability"
    DATA = "data"
    EXPORT = "export"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Penalty(BaseModel):
    """A single interpretable risk finding: reason + supporting source excerpt."""

    dimension: Dimension
    reason: str
    rule_id: str
    severity: int = Field(description="Raw penalty points before scaling (0-100)")
    excerpt: Optional[str] = Field(
        default=None, description="Verbatim source text the finding is based on"
    )
    para_index: Optional[int] = Field(
        default=None, description="0-based paragraph index in the input document"
    )
    keyword: Optional[str] = Field(
        default=None, description="Offending keyword/token that matched the rule"
    )


class DimensionScore(BaseModel):
    dimension: Dimension
    risk_level: RiskLevel
    raw_penalty: int = Field(description="Unnormalised gathered penalty points")
    normalized: float = Field(
        ge=0.0, le=100.0, description="0-100 score for this dimension"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)


class RiskReport(BaseModel):
    document_id: str
    overall_score: int = Field(ge=0, le=100, description="Explainable risk 0-100")
    overall_level: RiskLevel
    dimensions: List[DimensionScore]
    penalties: List[Penalty]
    summary: str
    deterministic_hash: str = Field(
        description="Hash of inputs + engine version; used to verify determinism"
    )


class DiffOp(str, Enum):
    ADD = "add"
    DELETE = "delete"
    MODIFY = "modify"


class DiffItem(BaseModel):
    """A leaf diff node: one marked change between the two documents."""

    op: DiffOp
    section: str = Field(description="Parent heading path, e.g. 'Article 3. Payment'")
    para_index_left: Optional[int] = Field(
        default=None, description="0-based index in left (template A) doc"
    )
    para_index_right: Optional[int] = Field(
        default=None, description="0-based index in right (template B) doc"
    )
    text_left: Optional[str] = Field(default=None, description="Original text (A side)")
    text_right: Optional[str] = Field(default=None, description="New text (B side)")
    summary: str = Field(description="Human-readable semantic summary of the change")


class DiffNode(BaseModel):
    """Recursive diff-tree node: section heading + children (sub-sections/items)."""

    label: str
    children: List["DiffNode"] = Field(default_factory=list)
    items: List[DiffItem] = Field(default_factory=list)


class DiffStats(BaseModel):
    additions: int
    deletions: int
    modifications: int


class DiffReport(BaseModel):
    """Full paragraph-level clause diff tree between two documents."""

    document_left: str
    document_right: str
    root: DiffNode
    stats: DiffStats
    summary: str


class FieldRun(BaseModel):
    """Result of extracting a key business field from a document."""

    name: str
    value: Optional[str] = None
    source: Optional[str] = None
    para_index: Optional[int] = None
    found: bool = False


class DocParse(BaseModel):
    document_id: str
    paragraphs: List[str]
    headings: List[int] = Field(
        default_factory=list, description="Indices into paragraphs that look like headings"
    )
    fields: List[FieldRun] = Field(default_factory=list)
    word_count: int = 0
