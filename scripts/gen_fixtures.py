"""Generate DOCX test fixtures programmatically.

Produces three template contracts (A/B/C) in both Chinese-first legal style and a
neutral English style header, with a high-risk and a low-risk risk fixture used
for calibration, plus a template-pair fixture used for the diff tree (30+ diffs).
"""

from __future__ import annotations

from pathlib import Path

import docx

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def _save(doc: docx.Document, name: str) -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / name
    doc.save(str(path))
    print(f"wrote {path}")


def _heading(doc: docx.Document, text: str) -> None:
    doc.add_heading(text, level=1)


def _para(doc: docx.Document, text: str) -> None:
    doc.add_paragraph(text)


# ---------------------------------------------------------------------------
# Template A: baseline
# ---------------------------------------------------------------------------
def template_a() -> docx.Document:
    doc = docx.Document()
    doc.add_heading("Service Agreement (Template A)", 0)
    _heading(doc, "Article 1. Term and Termination")
    _para(doc, "This agreement shall have an initial term of 12 months starting on the Effective Date.")
    _para(doc, "Either party may terminate this agreement for convenience upon 30 days written notice.")
    _heading(doc, "Article 2. Payment and Fees")
    _para(doc, "Customer shall pay an annual fee of $100,000 in quarterly installments.")
    _para(doc, "Provider may adjust the fees upon 60 days written notice to Customer.")
    _heading(doc, "Article 3. Intellectual Property")
    _para(doc, "Customer owns all intellectual property generated during the project.")
    _para(doc, "Provider grants Customer a perpetual, non-exclusive license to use the deliverables.")
    _heading(doc, "Article 4. Confidentiality")
    _para(doc, "Both parties shall maintain the confidentiality of the other party's information for 5 years after termination.")
    _para(doc, "Confidential information shall not be disclosed to any third party without prior written consent.")
    _heading(doc, "Article 5. Limitation of Liability")
    _para(doc, "In no event shall either party be liable for consequential, incidental or punitive damages.")
    _para(doc, "Each party's aggregate liability shall not exceed the fees paid in the previous 12 months.")
    _heading(doc, "Article 6. Data Protection")
    _para(doc, "Each party shall process personal data in accordance with applicable data protection law.")
    _para(doc, "Personal information shall only be used for the purpose of performing this agreement.")
    _heading(doc, "Article 7. Governing Law and Dispute Resolution")
    _para(doc, "This agreement shall be governed by the laws of England.")
    _para(doc, "Disputes shall be settled by arbitration administered by the LCIA in London.")
    _heading(doc, "Article 8. Export Compliance")
    _para(doc, "Customer shall comply with all applicable export control and sanctions laws.")
    return doc


# ---------------------------------------------------------------------------
# Template B: riskier variant (used for diff fixture against A)
# ---------------------------------------------------------------------------
def template_b() -> docx.Document:
    doc = docx.Document()
    doc.add_heading("Service Agreement (Template B)", 0)
    _heading(doc, "Article 1. Term and Termination")
    _para(doc, "This agreement shall automatically renew for successive 12-month terms unless either party provides written notice of termination at least 60 days before the end of the current term.")
    _para(doc, "Provider may terminate this agreement without cause at any time by delivering notice to Customer.")
    _heading(doc, "Article 2. Payment and Fees")
    _para(doc, "Customer shall pay an annual fee of $50,000 payable monthly in advance.")
    _para(doc, "Provider reserves the right to increase the prices at its own discretion each year.")
    _para(doc, "Customer shall pay all additional fees charged by Provider from time to time.")
    _heading(doc, "Article 3. Intellectual Property")
    _para(doc, "Provider owns all intellectual property generated during the project.")
    _heading(doc, "Article 4. Confidentiality")
    _para(doc, "Customer shall keep all information disclosed by Provider strictly confidential.")
    _para(doc, "Customer shall not disclose any information received from Provider to any third party.")
    _para(doc, "Confidential obligations survive termination for 3 years.")
    _heading(doc, "Article 5. Limitation of Liability")
    _para(doc, "In no event shall Provider be liable for any consequential, indirect, special, incidental or punitive damages, whether in contract, tort or otherwise.")
    _para(doc, "Provider's total aggregate liability shall not exceed the fees paid by Customer in the previous 3 months.")
    _heading(doc, "Article 6. Data Protection")
    _para(doc, "Customer grants Provider an unlimited, worldwide license to process personal data for any purpose.")
    _para(doc, "Provider may transfer personal data to its affiliates outside the European Union without prior notice.")
    _heading(doc, "Article 7. Governing Law and Dispute Resolution")
    _para(doc, "This agreement shall be governed by the laws of the State of New York.")
    _para(doc, "Disputes shall be resolved exclusively in the courts of New York County.")
    _heading(doc, "Article 8. Export Compliance")
    _para(doc, "Customer shall ensure that its products are not delivered to Cuba, Iran or any other sanctioned destination.")
    _para(doc, "Customer shall be solely responsible for obtaining any required export licenses.")
    _para(doc, "Customer shall not divert any technology delivered under this agreement without Provider authorization.")
    return doc


# ---------------------------------------------------------------------------
# Template C: third variant for calibrations / extra diff coverage
# ---------------------------------------------------------------------------
def template_c() -> docx.Document:
    doc = docx.Document()
    doc.add_heading("Service Agreement (Template C)", 0)
    _heading(doc, "Article 1. Term and Termination")
    _para(doc, "This agreement is effective for 24 months and may be renewed by mutual written agreement.")
    _para(doc, "Either party may terminate for convenience on 90 days notice.")
    _heading(doc, "Article 2. Payment")
    _para(doc, "Customer shall pay a flat fee of $300,000 upon signing.")
    _para(doc, "All fees are non-refundable and non-cancellable.")
    _heading(doc, "Article 3. Liability")
    _para(doc, "The services are provided as-is without warranties of any kind, express or implied.")
    _para(doc, "Provider shall not be liable for any indirect or consequential loss.")
    _heading(doc, "Article 5. Data")
    _para(doc, "No personal data shall be processed under this agreement.")
    _heading(doc, "Article 6. Law")
    _para(doc, "Governing law is Singapore; disputes are finally settled by SIAC arbitration in Singapore.")
    return doc


# ---------------------------------------------------------------------------
# Risk fixture: deliberately risky contract
# ---------------------------------------------------------------------------
def risky_contract() -> docx.Document:
    doc = docx.Document()
    doc.add_heading("Master Service Agreement", 0)
    _heading(doc, "1. Term")
    _para(doc, "This agreement shall automatically renew each year unless a party objects.")
    _para(doc, "Provider may terminate this agreement without cause, for any reason, at its convenience.")
    _heading(doc, "2. Fees")
    _para(doc, "Provider reserves the right to adjust the prices unilaterally and without consent.")
    _heading(doc, "3. IP & Assignment")
    _para(doc, "Customer assigns all intellectual property and may assign this agreement to any third party without consent.")
    _heading(doc, "4. Liability")
    _para(doc, "In no event shall Provider be liable for any consequential, indirect or special damages.")
    _para(doc, "Provider's aggregate liability is limited to the fees paid in the last 12 months.")
    _para(doc, "Customer shall indemnify Provider against all third-party claims and all damages.")
    _heading(doc, "5. Data")
    _para(doc, "Provider may process personal data for any purpose and transfer it outside the EU freely.")
    _para(doc, "Personal information may be shared with affiliated companies for product improvement.")
    _heading(doc, "6. Export")
    _para(doc, "Deliverables shall not be exported to Cuba, Iran, or North Korea.")
    _para(doc, "Customer is responsible for obtaining all export licenses.")
    _para(doc, "Provider accepts no responsibility for compliance with export control laws.")
    _heading(doc, "7. Law")
    _para(doc, "This agreement is governed by the laws of the State of Delaware.")
    return doc


# ---------------------------------------------------------------------------
# Risk fixture: clean contract (few findings)
# ---------------------------------------------------------------------------
def clean_contract() -> docx.Document:
    doc = docx.Document()
    doc.add_heading("Software License Agreement", 0)
    _heading(doc, "1. Term")
    _para(doc, "The license is granted for a fixed term of 24 months without auto-renewal.")
    _para(doc, "Either party may terminate for material breach after written notice and 30 days cure period.")
    _heading(doc, "2. Fees")
    _para(doc, "Fees are fixed for the term and may only change by written amendment signed by both parties.")
    _heading(doc, "3. IP & Assignment")
    _para(doc, "Licensee owns all its own intellectual property and improvements.")
    _para(doc, "Neither party may assign this agreement without the other party's prior written consent.")
    _heading(doc, "4. Liability")
    _para(doc, "Nothing in this agreement excludes liability for fraud, death or personal injury caused by negligence.")
    _para(doc, "Each party remains responsible for damages arising from its own gross negligence or willful misconduct.")
    _heading(doc, "5. Data")
    _para(doc, "Each party shall comply with GDPR and the Data Processing Agreement annex.")
    _para(doc, "Personal data shall only be processed for the purposes stated in the privacy policy.")
    _heading(doc, "6. Export")
    _para(doc, "Each party shall comply with applicable export control, sanctions and re-export laws.")
    _para(doc, "Technology transfers are subject to end-use controls and compliance screening.")
    _heading(doc, "7. Law")
    _para(doc, "This agreement is governed by English law with disputes referred to the London Court of International Arbitration.")
    return doc


def main() -> None:
    _save(template_a(), "template_a.docx")
    _save(template_b(), "template_b.docx")
    _save(template_c(), "template_c.docx")
    _save(risky_contract(), "risky_contract.docx")
    _save(clean_contract(), "clean_contract.docx")
    print("fixtures ready")


if __name__ == "__main__":
    main()
