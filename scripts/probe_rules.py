"""Probe audit: hunt over-fire (false positive) and under-fire (false negative)
gaps in the deterministic rule engine. Prints each probe case's hits.

Usage: .venv/bin/python scripts/probe_rules.py
"""

from lawrisk.rules import RULES, ABSENCE_RULES, _apply_paragraph_rules

SHOULD_NOT_FIRE = [
    # (label, paragraph)
    # R-COMM-6 over-fire area
    ("C-6 neg: escrow interest", "Funds held in escrow shall earn interest at 3% per annum, credited quarterly to the party entitled to them."),
    ("C-6 neg: price escalation tied to CPI", "The service fees shall be adjusted annually in accordance with the CPI index, not exceeding 5% per annum."),
    ("C-6 neg: statutory late payment interest", "Interest on overdue amounts accrues at the rate set by the Late Payment Act, which shall be the applicable statutory rate."),
    # R-COMM-3 over-fire
    ("C-3 neg: mutual price adjustment", "The parties may by mutual written agreement adjust the fees from time to time."),
    ("C-3 neg: no price increase", "Except as stated herein, there shall be no price increase during the term of this agreement."),
    # R-COMM-2 over-fire
    ("C-2 neg: mutual termination", "Either party may terminate this agreement upon 30 days' written notice."),
    ("C-2 neg: termination for cause", "Provider may terminate this agreement if Customer materially breaches and fails to cure within 15 days."),
    # R-COMM-5 over-fire
    ("C-5 neg: amendment with mutual consent", "Neither party shall amend, modify, alter, or vary this agreement except by mutual written consent of the parties."),
    ("C-5 neg: both parties may amend", "Both parties may from time to time amend the terms of this agreement by mutual written consent."),
    # R-COMM-8 over-fire
    ("C-8 neg: suspension for cause with notice", "Provider may suspend the services with immediate effect if Customer fails to pay undisputed invoices, provided it gives written notice of the non-payment."),
    ("C-8 neg: mutual suspension", "Either party may suspend its performance of this agreement where the other party is in material breach and fails to cure."),
    # R-LIAB-1 over-fire
    ("L-1 neg: mutual disclaimer", "Neither party shall be liable to the other for indirect or consequential losses, save for fraud, wilful misconduct and breach of confidentiality."),
    ("L-1 neg: exclusion carve-out", "In no event shall the provider be liable for indirect damages; nothing in this clause excludes liability for death or personal injury."),
    # R-LIAB-3 over-fire
    ("L-3 neg: each party indemnifies own breach", "Each party indemnifies the other against claims arising out of its own breach of this agreement."),
    ("L-3 neg: mutual indemnity", "The parties shall mutually indemnify each other against third-party claims to the extent caused by the indemnifying party's own negligence."),
    # R-DATA-1 over-fire
    ("D-1 neg: GDPR clause", "The parties shall comply with GDPR and the UK Data Protection Act 2018 when processing personal data under this agreement."),
    ("D-1 neg: denial of processing", "Neither party shall collect, process, use, share, or store personal data except as strictly necessary for performing this agreement."),
    # R-DATA-2 over-fire
    ("D-2 neg: SCC-backed transfer", "Customer personal data may be transferred to the provider's affiliate in the United States subject to the Standard Contractual Clauses approved by the European Commission."),
    ("D-2 neg: no transfer", "No transfer of personal data to third countries shall occur under this agreement."),
    # R-DATA-3 over-fire
    ("D-3 neg: purpose-limited processing", "Provider shall process personal data solely to provide the services and for no other purpose, in accordance with data minimisation principles."),
    # R-EXP-1 over-fire
    ("E-1 neg: compliance statement", "Each party shall comply with all applicable export control and sanctions laws and shall obtain any required export licences."),
    ("E-1 neg: in compliance", "The services are provided in compliance with all applicable export and sanctions regulations."),
    # R-EXP-3 over-fire
    ("E-3 neg: prior authorisation", "No re-export or diversion of the software shall occur without the prior written authorisation of the licensor."),
    # R-LIAB-4 over-fire
    ("L-4 neg: strict warranty clause", "Provider warrants the services will be free from defects; the as-is language in the previous recitals does not apply to the warranties in this clause."),
    ("L-4 neg: as-is with warranty carve", "The software is provided as-is; however, the warranties set forth in Section 5 shall apply."),
]

SHOULD_FIRE = [
    # R-COMM-3 under-fire
    ("C-3 pos: may increase fees", "Provider may increase the monthly fees at any time upon 30 days' prior written notice to Customer."),
    # R-COMM-2 under-fire
    ("C-2 pos: terminate for convenience", "Company may terminate this agreement at any time for its convenience without cause and without penalty."),
    # R-COMM-5 under-fire
    ("C-5 pos: revise terms at sole discretion", "Provider reserves the right to revise these terms at its sole discretion from time to time, with updates posted on its website."),
    # R-COMM-6 under-fire
    ("C-6 pos: 1.5% monthly on unpaid invoices", "Any amounts not paid when due shall accrue interest at one and one-half percent (1.5%) per month on the unpaid balance until paid."),
    ("C-6 pos: $250 monthly late fee", "A monthly late fee of $250 shall be charged for each late payment, assessed monthly until the overdue balance is paid in full."),
    # R-COMM-8 under-fire
    ("C-8 pos: suspend access at sole discretion", "Provider may suspend or deactivate any account or the services at its sole discretion at any time, without notice and with immediate effect."),
    # R-LIAB-3 under-fire
    ("L-3 pos: broad indemnity by customer", "Customer shall indemnify and hold harmless Provider against any and all claims, losses and damages arising from Customer's use of the services."),
    # R-DATA-3 under-fire
    ("D-3 pos: process for own purposes", "Provider may process Customer data for its own independent purposes, including machine learning model training, without limitation."),
    # R-EXP-2 under-fire
    ("E-2 pos: cuba reference no carve", "Orders shall be fulfilled worldwide; the vendor maintains a sales office in Tehran and ships directly to customers in Cuba."),
    # R-LIAB-6 under-fire
    ("L-6 pos: penalty per day", "A penalty of $500 per day for each day of delay shall be paid by the supplier to the buyer."),
    ("L-6 pos: liquidated damages forfeit", "Liquidated damages in the fixed sum of $10,000 shall be forfeited upon any delay in delivery, without proof of actual loss."),
    # R-LIAB-2 under-fire
    ("L-2 pos: cap at fees", "Provider's aggregate liability arising out of or related to this agreement shall not exceed the fees paid in the twelve months preceding the claim."),
    # R-COMM-4 under-fire
    ("C-4 pos: assign to third party no consent", "Customer may assign this agreement to any third party without the prior written consent of Provider."),
    # R-COMM-7 under-fire
    ("C-7 pos: non-refundable fees", "All fees paid under this agreement are final, non-refundable and non-cancellable once the services have been provisioned."),
    # R-EXP-3 under-fire
    ("E-3 pos: no export control", "The software is deliverable worldwide; Customers may re-export the software to any country or use it for any end-use."),
]


def main() -> None:
    print("=== NEGATIVE (should NOT fire) ===")
    total_bad = 0
    for label, para in SHOULD_NOT_FIRE:
        hits = [r.rule_id for r in _apply_paragraph_rules([para], RULES)]
        status = "FIRE!" if hits else "ok"
        if hits:
            total_bad += 1
        print(f"[{status}] {label} -> {hits}")
    print()
    print(f"NEGATIVE over-fire count: {total_bad}")
    print()
    print("=== POSITIVE (should fire) ===")
    missed = 0
    for label, para in SHOULD_FIRE:
        hits = [r.rule_id for r in _apply_paragraph_rules([para], RULES)]
        status = "MISSED!" if not hits else "ok"
        if not hits:
            missed += 1
        print(f"[{status}] {label} -> {hits}")
    print()
    print(f"POSITIVE under-fire count: {missed}")


if __name__ == "__main__":
    main()
