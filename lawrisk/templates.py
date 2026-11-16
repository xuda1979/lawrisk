"""P3: reusable clause-template library.

A small registry of clause templates a law firm can diff their incoming
agreement against. Templates are plain-text definitions (kept here so they are
versioned with the codebase and reproducible offline), wrapped by a REST API
and a CLI dump script.

Design (低算力守则): pure data + deterministic lookups; no network, no LLM.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List

from lawrisk.diff.differ import build_diff_tree
from lawrisk.models import DiffReport
from lawrisk.textutil import split_paragraphs


@dataclass(frozen=True)
class ClauseTemplate:
    """A named, curated clause set used as a comparison baseline."""

    id: str
    name: str
    description: str = ""
    sections: List[str] = field(default_factory=list)
    paragraphs: List[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "sections": self.sections,
            "paragraph_count": len(self.paragraphs),
            "content_hash": self.content_hash,
        }

    @property
    def content_hash(self) -> str:
        payload = "\n".join(self.paragraphs).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def _tpl(
    id: str,
    name: str,
    description: str,
    sections: List[str],
    paragraphs: List[str],
) -> ClauseTemplate:
    return ClauseTemplate(
        id=id,
        name=name,
        description=description,
        sections=sections,
        paragraphs=paragraphs,
    )


# One baseline template per common contracting pattern. Paragraphs are grouped
# by section; the diff engine will re-split them into the section structure.
DEFAULT_TEMPLATES: List[ClauseTemplate] = [
    _tpl(
        id="msa",
        name="Master Services Agreement (baseline)",
        description=(
            "Balanced MSA baseline: mutual termination, capped mutual liability, "
            "GDPR-aware data handling and export-compliance affirmations."
        ),
        sections=[
            "Term and Termination",
            "Payments",
            "Intellectual Property",
            "Confidentiality",
            "Limitation of Liability",
            "Data Protection",
            "Export Compliance",
        ],
        paragraphs=[
            "1. Term. The initial term of this Agreement is 12 months and renews "
            "for successive terms only where both parties agree in writing.",
            "1.1 Either party may terminate this Agreement for convenience upon "
            "30 days prior written notice to the other party.",
            "2. Payments. Fees are fixed for the initial term and may only be "
            "changed by written amendment signed by both parties.",
            "2.1 All invoices are payable within 30 days of the invoice date.",
            "3. Intellectual Property. Each party retains ownership of its own "
            "pre-existing intellectual property.",
            "4. Confidentiality. Each party shall hold the other's confidential "
            "information in confidence for 5 years after termination.",
            "5. Limitation of Liability. In no event shall either party be liable "
            "for indirect, consequential or special damages, and each party's "
            "aggregate liability shall not exceed the fees paid in the last 12 "
            "months.",
            "5.1 Nothing in this Agreement excludes liability for fraud, death or "
            "personal injury caused by negligence.",
            "6. Data Protection. Each party shall process personal data in "
            "accordance with applicable data protection law and the Data Processing "
            "Agreement.",
            "7. Export Compliance. Each party shall comply with all applicable "
            "export control and sanctions laws.",
        ],
    ),
    _tpl(
        id="sps",
        name="Software & SaaS subscription (baseline)",
        description=(
            "SaaS-friendly baseline: subscription term, guaranteed uptime "
            "warranties, service-level credits and a clean data exit path."
        ),
        sections=[
            "Subscription Term",
            "Service Levels",
            "Data",
        ],
        paragraphs=[
            "1. Subscription. The subscription term is 12 months and does not "
            "auto-renew without the Customer's prior written consent.",
            "2. Service Levels. Provider shall maintain an uptime of at least "
            "99.5% measured monthly.",
            "2.1 If uptime falls below the commitment, Customer is entitled to a "
            "service credit against the next invoice.",
            "3. Data. Customer owns all data it uploads to the services.",
            "3.1 On termination, Provider shall return or delete Customer data "
            "within 30 days at Customer's election.",
        ],
    ),
    _tpl(
        id="nda",
        name="Mutual Non-Disclosure Agreement (baseline)",
        description=(
            "Short mutual NDA baseline with a clear obligations window and no "
            "open-ended confidentiality duties."
        ),
        sections=[
            "Confidential Information",
            "Survival",
        ],
        paragraphs=[
            "1. Confidential Information means information disclosed in writing "
            "and marked confidential by the disclosing party.",
            "2. Each party shall use the same care to protect Confidential "
            "Information as it uses for its own similar information.",
            "3. These confidentiality obligations survive for 3 years after "
            "termination of this agreement.",
        ],
    ),
    _tpl(
        id="saas-dpa",
        name="Data Processing Agreement (baseline)",
        description=(
            "DPA baseline following the GDPR Article 28 skeleton: processor "
            "obligations, sub-processor notice, assistance and deletion duties."
        ),
        sections=[
            "Processing",
            "Sub-processors",
            "Security",
        ],
        paragraphs=[
            "1. The Processor shall process personal data only on documented "
            "instructions from the Controller.",
            "2. The Processor shall not engage a sub-processor without the "
            "Controller's prior written authorisation.",
            "3. The Processor shall implement appropriate technical and "
            "organisational measures to ensure a level of security appropriate "
            "to the risk.",
            "4. The Processor shall assist the Controller with data subject "
            "requests and shall delete or return all personal data on termination.",
        ],
    ),
]

_TEMPLATES_BY_ID = {t.id: t for t in DEFAULT_TEMPLATES}


def list_templates() -> List[ClauseTemplate]:
    return list(DEFAULT_TEMPLATES)


def get_template(template_id: str) -> ClauseTemplate | None:
    return _TEMPLATES_BY_ID.get(template_id)


def diff_against_template(
    paragraphs: List[str],
    template_id: str,
    document_name: str = "Document",
) -> DiffReport:
    """Diff a parsed document against a named baseline template."""
    tpl = get_template(template_id)
    if tpl is None:
        raise KeyError(f"unknown template id: {template_id!r}")
    return build_diff_tree(
        split_paragraphs("\n\n".join(tpl.paragraphs)),
        paragraphs,
        f"Template {template_id} ({tpl.name})",
        document_name,
    )
