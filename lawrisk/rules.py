"""Deterministic, keyword/rule-based risk scoring engine.

Design rules ("低算力守则"): everything is compiled regex over the already
extracted paragraphs + extracted fields. No randomness, no external calls, so
identical input always yields the identical score (AC1). Every penalty carries a
human-readable reason and a verbatim source excerpt (AC2).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import List

from lawrisk.models import (
    Dimension,
    DimensionScore,
    Penalty,
    RiskLevel,
    RiskReport,
)
from lawrisk.textutil import looks_like_heading

ENGINE_VERSION = "lawrisk-engine-v1"

# Maximum number of exemplars kept per rule so long docs stay readable.
MAX_CITES_PER_RULE = 3

# Weights used to aggregate dimension scores into the 0-100 overall score.
DIM_WEIGHTS = {
    Dimension.COMMERCIAL: 0.35,
    Dimension.LIABILITY: 0.30,
    Dimension.DATA: 0.20,
    Dimension.EXPORT: 0.15,
}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    dimension: Dimension
    pattern: re.Pattern[str]
    severity: int
    reason: str
    condition: re.Pattern[str] | None = None
    exclusion: re.Pattern[str] | None = None
    description: str = ""
    mitigation: str = ""


_CARVEOUT = re.compile(
    r"(?:unless|except|provided that|provided it gives|if[^.]{0,25}(?:notice|consent|object))",
    re.IGNORECASE,
)
_MUTUAL = re.compile(r"(?:either|each|both|any)\s+(?:party|parties)", re.IGNORECASE)

RULES: List[Rule] = [
    # ---------------------------------------------------------------- commercial
    Rule(
        rule_id="R-COMM-1",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(r"auto[- ]?renew|renew automatically|automatically renew", re.IGNORECASE),
        exclusion=re.compile(r"(?:no auto[- ]?renewal|without auto[- ]?renewal|does not auto[- ]?renew)", re.IGNORECASE),
        severity=20,
        reason="Automatic renewal without an explicit opt-out window",
        mitigation="Require explicit written opt-in for renewal, add a >60 day renewal notice window, or remove auto-renewal.",
    ),
    Rule(
        rule_id="R-COMM-2",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(r"terminate[^.]{0,40}(?:without cause|for any reason|at (?:its|our|the (?:provider|company)) ?(?:own )?convenience|for convenience)", re.IGNORECASE),
        exclusion=re.compile(r"(?:{})|(?:{})".format(_CARVEOUT.pattern, _MUTUAL.pattern), re.IGNORECASE),
        severity=25,
        reason="One-sided termination-without-cause right for the counterparty",
        mitigation="Make termination rights mutual — require cause, mutual consent, or equal notice/fee windows for both parties.",
    ),
    Rule(
        rule_id="R-COMM-3",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(r"reserves the right to (?:adjust|increase|change|modify) (?:the )?(?:price|prices|fees)|price (?:increase|escalation)", re.IGNORECASE),
        severity=20,
        reason="Unilateral price adjustment clause without consent requirement",
        mitigation="Cap annual fee increases at a fixed percentage with 60+ days written notice, or require mutual written consent.",
    ),
    Rule(
        rule_id="R-COMM-4",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(r"assign\s*:\s*|assign(?: this agreement)?[^.]{0,40}(?:without[^.]{0,30}consent|to any third party)|transfer this agreement[^.]{0,30}without", re.IGNORECASE),
        severity=20,
        reason="Assignment without the other party's prior written consent",
        mitigation="Add mutual prior-written-consent approval for any assignment, and carve out assignment to an affiliate.",
    ),
    Rule(
        rule_id="R-COMM-5",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(
            r"(?:"
            r"(?:may|can|reserves? the right to|is (?:entitled|authorised|authorized) to)"
            r"[^.]{0,30}"
            r"(?:amend|modify|alter|vary|change|revise)\s+"
            r"(?:this agreement|these presents|the terms|the terms and conditions|"
            r"any (?:of the )?(?:term|provision|clause|condition)s?[^.]{0,8}hereof)"
            r"[^.]{0,35}"
            r"(?:at any time|at (?:its|his|their)? ?(?:own )?(?:sole|absolute) discretion|"
            r"without (?:prior )?(?:notice|consent|approval)|unilaterally)"
            r")",
            re.IGNORECASE,
        ),
        exclusion=_MUTUAL,
        severity=20,
        reason="Unilateral amendment of the agreement or its terms without mutual written consent",
        mitigation="Require amendments to be agreed in writing by both parties; allow only limited, notice-based administrative changes.",
    ),
    Rule(
        rule_id="R-COMM-6",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(
            r"late payment(?:s)?[^.]{0,40}(?:interest|penalty|fee)|"
            r"interest[^.]{0,20}(?:at|of|=)[^.]{0,25}(?:per month|per annum|%|percent)",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Late-payment interest/penalty applies to the counterparty above market rates",
        mitigation="Cap late-payment interest at a statutory or market rate and add a grace period before interest accrues.",
    ),
    Rule(
        rule_id="R-COMM-7",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(r"non[ -]?refundable(?: and non[ -]?cancellable)?|non[ -]?cancellable", re.IGNORECASE),
        severity=15,
        reason="Fees are non-refundable / non-cancellable, locking the counterparty into payment",
        mitigation="Allow pro-rata refunds or termination credits for unused services and carve out cancellation-for-cause.",
    ),
    Rule(
        rule_id="R-COMM-8",
        dimension=Dimension.COMMERCIAL,
        pattern=re.compile(
            r"(?:suspend|deactivate)[^.]{0,60}"
            r"(?:the services|services|access|the account|any account)"
            r"[^.]{0,50}"
            r"(?:without (?:prior )?(?:notice|consent|warning)|"
            r"at any time|"
            r"at (?:its|our|provider'?s)[^.]{0,15}(?:sole|absolute)[^.]{0,15}(?:discretion)|"
            r"with immediate effect)",
            re.IGNORECASE,
        ),
        exclusion=re.compile(r"(?:{})|(?:{})".format(_CARVEOUT.pattern, _MUTUAL.pattern), re.IGNORECASE),
        severity=20,
        reason="Unilateral suspension of services/account by the counterparty without notice or consent",
        mitigation="Require notice, a cure period and cause for any suspension, and credit for service downtime.",
    ),
    # ----------------------------------------------------------------- liability
    Rule(
        rule_id="R-LIAB-1",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(r"((?:in no event|under no circumstances)) (?:shall|will) (?:the )?(provider|company)|(?:provider|company) shall not (?:be liable|have any liability) for", re.IGNORECASE),
        exclusion=re.compile(r"(?:fraud|death|personal injury|gross negligence|wilful misconduct|willful misconduct|neither party|both parties|each party|either party)", re.IGNORECASE),
        severity=25,
        reason="Broad disclaimer covering consequential/indirect damages",
        mitigation="Carve out fraud, death or personal injury, gross negligence and willful misconduct from the exclusion.",
    ),
    Rule(
        rule_id="R-LIAB-2",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(r"(?:total |aggregate |maximum )?liability[^.]{0,40}limited to", re.IGNORECASE),
        severity=25,
        reason="Aggregate liability cap may be below expected exposure",
        mitigation="Negotiate a cap that covers realistically foreseeable loss; base it on fees for 12 months or more.",
    ),
    Rule(
        rule_id="R-LIAB-3",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(r"indemnif(?:y|ies)[^.]{0,20}(?:against|from)[^.]{0,40}(?:all|any|third[ -]party|losses|damages|claims)", re.IGNORECASE),
        severity=30,
        reason="Broad indemnification obligation in favour of the counterparty",
        mitigation="Limit indemnity to third-party IP- or breach-specific claims and add mutual caps and carve-outs.",
    ),
    Rule(
        rule_id="R-LIAB-4",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(r"(?:as[ -]is|without (?:any )?warrant(?:y|ies))", re.IGNORECASE),
        severity=30,
        reason='"As-is" delivery with warranties disclaimed',
        mitigation="Restore basic warranties (conformity, availability) and remove absolute as-is disclaimers.",
    ),
    Rule(
        rule_id="R-LIAB-5",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(
            r"(?:does not|will not|shall not|makes? no)[^.]{0,40}"
            r"(?:warrant(?:y|ies?)?|guarantee|represent)[^.]{0,40}"
            r"(?:uninterrupted|error[- ]?free|available|fit for)",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Availability / quality of services is disclaimed (interruption or error-free operation not warranted)",
        mitigation="Add service-level and availability commitments with remedies for sustained downtime.",
    ),
    Rule(
        rule_id="R-LIAB-6",
        dimension=Dimension.LIABILITY,
        pattern=re.compile(
            r"liquidated damages[^.]{0,80}(?:forfeit|penalty|per[ -]?(?:day|week|month|occurrence|event)|"
            r"fixed (?:amount|sum))|"
            r"liquidated damages\b",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:no|not|exclude(e?d)?|only|solely|cap(?:ed)?|limited to|"
            r"genuine pre[- ]?estimate|reasonable estimate|proportionate)",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Liquidated-damages / penalty clause may allow disproportionate recovery",
        mitigation="Cap liquidated damages at a genuine pre-estimate of loss; avoid penalty-style per-day accrual without a bound.",
    ),
    # ------------------------------------------------------------------- data
    Rule(
        rule_id="R-DATA-5",
        dimension=Dimension.DATA,
        pattern=re.compile(
            r"(?:data|information)[^.]{0,60}"
            r"(?:shall (?:be )?(?:retained?|kept)|may (?:be )?(?:retained?|kept))"
            r"[^.]{0,40}(?:after|following|upon) (?:termination|such termination)",
            re.IGNORECASE,
        ),
        exclusion=re.compile(
            r"(?:require|required|obligat|as (?:required|needed)|in accordance with|"
            r"only for|solely|necessary to (?:comply|fulfil|fulfill)|legal obligation|"
            r"not (?:be )?(?:retained|kept))",
            re.IGNORECASE,
        ),
        severity=20,
        reason="Customer data may be retained after termination without a bounded, consent-limited basis",
        mitigation="Bound post-termination data retention to legal requirements, delete or return data within a defined window after term.",
    ),
    Rule(
        rule_id="R-DATA-1",
        dimension=Dimension.DATA,
        pattern=re.compile(r"personal (?:data|information)|personally identifiable", re.IGNORECASE),
        exclusion=re.compile(r"(?:gdpr|ccpa|data protection|privacy policy|dpa\b|data processing agreement|comply (?:with|ing)|shall only be (?:used|processed)|only for the purpose|purpose of performing)", re.IGNORECASE),
        severity=20,
        reason="Personal data is in scope; GDPR/CCPA obligations arise",
        mitigation="Confirm a lawful basis, a completed DPIA where needed, and a signed DPA annex with the counterparty.",
    ),
    Rule(
        rule_id="R-DATA-2",
        dimension=Dimension.DATA,
        pattern=re.compile(r"transfer[^.]{0,30}(?:personal )?data[^.]{0,30}(?:outside|abroad|to third|to (?:its|our) (?:affiliates?|subprocessors))", re.IGNORECASE),
        severity=35,
        reason="Cross-border / third-party data transfer without stated safeguards",
        mitigation="Add standard contractual clauses, adequacy findings, or equivalent transfer safeguards before any transfer.",
    ),
    Rule(
        rule_id="R-DATA-3",
        dimension=Dimension.DATA,
        pattern=re.compile(r"process[^.]{0,30}data[^.]{0,20}(?:for any purpose|for (?:its|our) own(?: independent)? purposes|unlimited)", re.IGNORECASE),
        severity=25,
        reason="Data processing purpose may be too broad / unlimited",
        mitigation="Restrict processing to documented, purpose-limited activities and add data minimisation wording.",
    ),
    # ------------------------------------------------------------------ export
    Rule(
        rule_id="R-EXP-1",
        dimension=Dimension.EXPORT,
        pattern=re.compile(r"\b(?:exports?|sanctions?|embargoes?|bribery|anti[- ]corruption|itar|deemed exports?)\b", re.IGNORECASE),
        exclusion=re.compile(
            r"(?:comply (?:with|ing)|in compliance|subject to (?:applicable )?(?:export|sanction)|responsible for obtaining|shall ensure|shall obtain|shall be responsible|counter[- ]sanctions|applicable (?:export control|sanctions) laws)",
            re.IGNORECASE,
        ),
        severity=25,
        reason="Export/sanctions obligations appear but supporting controls are not visible in this clause",
        mitigation="Add a dedicated export-compliance clause and confirm which party owns export classification and licensing.",
    ),
    Rule(
        rule_id="R-EXP-2",
        dimension=Dimension.EXPORT,
        condition=re.compile(r"export|sanctions|embargo", re.IGNORECASE),
        pattern=re.compile(r"\b(cuba|iran|syria|north korea|crimea)\b", re.IGNORECASE),
        severity=50,
        reason="References to a sanctioned jurisdiction without a compliance carve-out",
        mitigation="Remove any sanctioned-destination references or add an explicit sanctions-compliance and export-license carve-out.",
    ),
    Rule(
        rule_id="R-EXP-3",
        dimension=Dimension.EXPORT,
        condition=re.compile(r"deliver|ship|supply|technology|software", re.IGNORECASE),
        pattern=re.compile(r"(?:re[- ]?export|diversion|end[- ]?use)", re.IGNORECASE),
        exclusion=re.compile(r"(?:subject to|comply|controls|restrictions|screening|authorization|authorisation)", re.IGNORECASE),
        severity=30,
        reason="No export/re-export or diversion controls for deliverables",
        mitigation="Add re-export and end-use control language; require end-user screening and any relevant licences.",
    ),
]

# Document-level absence checks: if the condition keyword/phrase appears but no
# protective term is present anywhere, flag the first matching paragraph.
ABSENCE_RULES: List[Rule] = [
    Rule(
        rule_id="R-DATA-4",
        dimension=Dimension.DATA,
        condition=re.compile(r"personal (?:data|information)", re.IGNORECASE),
        pattern=re.compile(r"data (?:protection|controller|processor)|GDPR|CCPA|privacy policy|data processing agreement|DPA\b", re.IGNORECASE),
        severity=20,
        reason="Personal data handled but no data-protection / DPA terms found",
        mitigation="Add data-protection wording and a signed DPA (or flow-down) before any personal-data processing.",
    ),
    Rule(
        rule_id="R-EXP-4",
        dimension=Dimension.EXPORT,
        condition=re.compile(r"export|international|deliverables", re.IGNORECASE),
        pattern=re.compile(r"export control|compliance with (?:applicable )?(?:export|sanctions)|sanctions compliance", re.IGNORECASE),
        severity=25,
        reason="Export activities likely, but no export-compliance clause found",
        mitigation="Include an export-control and sanctions-compliance clause and allocate licence responsibility clearly.",
    ),
]

_DIMENSION_NAMES = {
    Dimension.COMMERCIAL: "Commercial risk",
    Dimension.LIABILITY: "Liability / legal risk",
    Dimension.DATA: "Data protection",
    Dimension.EXPORT: "Export compliance",
}

# Absence rules fire only when the topic is present but protective wording is
# missing; kept out of the plain regex-free serialisation below because they
# carry no literal match pattern of their own.
KIND_PARAGRAPH = "paragraph"
KIND_ABSENCE = "absence"


def rule_catalog() -> list[dict]:
    """Serialise the full rule set for the /api/rules handbook endpoint.

    Each entry is a plain dict (no compiled regex survives serialisation):
    id, dimension, severity, reason, mitigation, description and kind
    (paragraph vs document-level absence check). Pattern fragments are exposed
    as-is (source is public) so the handbook can explain what triggers a rule.
    """
    catalog: list[dict] = []
    for kind, rules in ((KIND_PARAGRAPH, RULES), (KIND_ABSENCE, ABSENCE_RULES)):
        for rule in rules:
            entry = {
                "rule_id": rule.rule_id,
                "dimension": rule.dimension.value,
                "dimension_label": _DIMENSION_NAMES[rule.dimension],
                "severity": rule.severity,
                "reason": rule.reason,
                "mitigation": rule.mitigation,
                "description": rule.description,
                "kind": kind,
                "has_condition": rule.condition is not None,
                "has_exclusion": rule.exclusion is not None,
            }
            if rule.pattern is not None:
                entry["pattern"] = rule.pattern.pattern
            if rule.condition is not None:
                entry["condition"] = rule.condition.pattern
            catalog.append(entry)
    return catalog


def _trim(text: str, limit: int = 240) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _pick(candidates: List[Penalty]) -> List[Penalty]:
    """Deterministically cap citations so a rule contributes <= N exemplars."""
    return candidates[:MAX_CITES_PER_RULE]


def _apply_paragraph_rules(
    paragraphs: List[str], rules: List[Rule]
) -> List[Penalty]:
    penalties: List[Penalty] = []
    for rule in rules:
        hits: List[Penalty] = []
        for i, para in enumerate(paragraphs):
            if looks_like_heading(para):
                continue
            normalized = para.casefold()
            if rule.condition is not None and not rule.condition.search(normalized):
                continue
            m = rule.pattern.search(normalized)
            if m and rule.exclusion and rule.exclusion.search(normalized):
                continue
            if m:
                hits.append(
                    Penalty(
                        dimension=rule.dimension,
                        reason=rule.reason,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        excerpt=_trim(para),
                        para_index=i,
                        keyword=m.group(0)[:80],
                        mitigation=rule.mitigation,
                    )
                )
        penalties.extend(_pick(hits))
    return penalties


def _apply_absence_rules(paragraphs: List[str], rules: List[Rule]) -> List[Penalty]:
    full = "\n".join(paragraphs).casefold()
    penalties: List[Penalty] = []
    for rule in rules:
        # Trigger only when the topic IS present but the protective term is not.
        m = rule.condition.search(full)
        if not m:
            continue
        if rule.pattern.search(full):
            continue
        # Anchor the finding on a real body paragraph, never a heading, so the
        # excerpt points at the clause that raised the topic. If the topic only
        # appears inside headings (e.g. a "PERSONAL DATA" section title), fall
        # back to that heading as the closest verbatim source.
        body_hit = next(
            (
                i
                for i, p in enumerate(paragraphs)
                if not looks_like_heading(p) and rule.condition.search(p.casefold())
            ),
            None,
        )
        if body_hit is None:
            body_hit = next(
                (i for i, p in enumerate(paragraphs) if rule.condition.search(p.casefold())),
                None,
            )
        if body_hit is None:
            continue
        penalties.append(
            Penalty(
                dimension=rule.dimension,
                reason=rule.reason,
                rule_id=rule.rule_id,
                severity=rule.severity,
                excerpt=_trim(paragraphs[body_hit]),
                para_index=body_hit,
                keyword=None,
                mitigation=rule.mitigation,
            )
        )
    return penalties


def _level(score: int) -> RiskLevel:
    if score >= 66:
        return RiskLevel.HIGH
    if score >= 33:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _confidence(n_exemplars: int) -> float:
    """Deterministic confidence derived purely from evidence volume."""
    return round(min(0.95, 0.30 + 0.10 * n_exemplars), 2)


def score_document(paragraphs: List[str], document_id: str) -> RiskReport:
    """Compute a fully deterministic, explainable risk report."""
    penalties = _apply_paragraph_rules(paragraphs, RULES)
    penalties += _apply_absence_rules(paragraphs, ABSENCE_RULES)

    per_dim: dict[Dimension, int] = {}
    for dim in Dimension:
        per_dim[dim] = min(
            100, sum(p.severity for p in penalties if p.dimension is dim)
        )

    dimensions: List[DimensionScore] = []
    for dim in Dimension:
        raw = per_dim[dim]
        n_ex = sum(1 for p in penalties if p.dimension is dim)
        score = min(100.0, round(raw))
        dims = DimensionScore(
            dimension=dim,
            risk_level=_level(int(score)),
            raw_penalty=raw,
            normalized=score,
            confidence=_confidence(n_ex),
            reasons=[f"{p.reason} (excerpt #{p.para_index + 1})" for p in penalties if p.dimension is dim][:8]
            or [f"No material {_DIMENSION_NAMES[dim].lower()} concerns identified."],
        )
        dimensions.append(dims)

    weighted = sum(DIM_WEIGHTS[d.dimension] * d.normalized for d in dimensions)
    overall = int(round(weighted))

    # Determinism hash: content + engine version, so AC1 is machine-verifiable.
    digest = hashlib.sha256(
        "\n".join(paragraphs).encode("utf-8") + f"\nINCLUDES:{ENGINE_VERSION}".encode("utf-8")
    ).hexdigest()

    high = sum(1 for d in dimensions if d.risk_level is RiskLevel.HIGH)
    mid = sum(1 for d in dimensions if d.risk_level is RiskLevel.MEDIUM)
    n_pen = len(penalties)

    if high >= 3 or overall >= 66:
        summary = (
            f"High-risk agreement: {overall}/100 overall. {n_pen} findings across "
            f"{high} high-risk dimension(s) ({', '.join(_DIMENSION_NAMES[d.dimension] for d in dimensions if d.risk_level is RiskLevel.HIGH)}). "
            "Review termination, indemnity and data clauses together with the counterparty."
        )
    elif overall >= 33:
        summary = (
            f"Medium-risk agreement: {overall}/100 overall. {n_pen} findings; {mid} "
            "dimension(s) show moderate exposure. Targeted review recommended before signature."
        )
    else:
        summary = (
            f"Low-risk agreement: {overall}/100 overall. {n_pen} minor findings; "
            "standard protective wording appears to be in place."
        )

    return RiskReport(
        document_id=document_id,
        overall_score=overall,
        overall_level=_level(overall),
        dimensions=dimensions,
        penalties=penalties,
        summary=summary,
        deterministic_hash=digest,
    )
