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
    # cycle 46 R-LIAB-1 over-fire (modal-less + verb-form disclaimers)
    ("L-1 neg: either party is not liable", "Either party is not liable for any indirect or consequential damages."),
    ("L-1 neg: each party has no liability", "Each party shall have no liability to the other for indirect damages."),
    ("L-1 neg: both parties not liable each other", "Both parties shall not be liable to each other for consequential damages arising from use of the services."),
    ("L-1 neg: carve-out fraud present tense", "The provider is not liable for consequential damages, except in cases of fraud or gross negligence."),
    ("L-1 neg: carve-out gross negligence accepts", "The vendor accepts no liability for indirect damages other than for losses caused by the supplier's gross negligence."),
    # R-LIAB-3 over-fire
    ("L-3 neg: each party indemnifies own breach", "Each party indemnifies the other against claims arising out of its own breach of this agreement."),
    ("L-3 neg: mutual indemnity", "The parties shall mutually indemnify each other against third-party claims to the extent caused by the indemnifying party's own negligence."),
    # cycle 45 R-LIAB-3 over-fire (named-party own-fault)
    ("L-3 neg: buyer own breach", "Buyer shall indemnify Seller against claims arising out of Buyer's own breach of contract."),
    ("L-3 neg: customer own negligence hold", "Customer shall hold Provider harmless against any claims arising from Customer's own negligence."),
    ("L-3 neg: vendor to extent caused by own", "Vendor shall indemnify Purchaser to the extent caused by Vendor's own negligence."),
    # cycle 45 R-LIAB-3 over-fire (mutual 'for' connector own-fault)
    ("L-3 neg: each party for its own negligence", "Each party shall indemnify the other for any loss or damage caused by its own negligence."),
    ("L-3 neg: the parties for their own", "The parties shall indemnify each other for any loss caused by their own negligence."),
    ("L-3 neg: both parties respective own acts", "Both parties shall indemnify each other for any claims arising from their respective own acts."),
    ("L-3 neg: cross-indemnify own breach", "The parties shall cross-indemnify each other for losses caused by the indemnifying party's own breach."),
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
    ("L-4 neg: each party makes no warranties", "Each party makes no warranties of any kind with respect to its own pre-contractual statements."),
    # R-DATA-1/R-DATA-2 over-fire
    ("D-2 neg: adequacy determination transfer", "Personal data may be transferred to the United States following an adequacy determination by the European Commission."),
    # R-EXP-2 over-fire
    ("E-2 neg: sanctions compliance mentions Sudan/Myanmar", "Each party shall comply with all applicable sanctions, including those covering Sudan and Myanmar."),
    # cycle 7 R-EXP-3 over-fire
    ("E-3 neg: EULA end-user", "Customer may install the software under the terms of the End User License Agreement."),
    # cycle 7 R-EXP-1/R-EXP-2 over-fire
    ("E-2 neg: excluding Crimea", "The services shall be available worldwide, excluding Crimea and other sanctioned regions."),
    # cycle 7 R-DATA-1 over-fire
    ("D-1 neg: privacy policy processing", "The parties shall process personal data in accordance with the Privacy Policy available at the provider's website."),
    # cycle 7 R-DATA-3 over-fire
    ("D-3 neg: aggregate anonymised statistics", "Provider may retain aggregate, anonymised data for statistical purposes without limitation."),
    # cycle 7 R-COMM-2 over-fire
    ("C-2 neg: either party may terminate", "This agreement may be terminated by either party upon 30 days' written notice."),
    # cycle 7 R-COMM-3 over-fire
    ("C-3 neg: fees may be reduced", "The fees may be reduced by Provider if usage volume exceeds 1,000 units."),
    # cycle 7 R-EXP-3 over-fire
    ("E-3 neg: no re-export without authorisation", "Buyer shall not re-export the software to any country without the prior written authorisation of the Licensor."),
    # cycle 7 R-DATA-2 over-fire
    ("D-2 neg: SCC transfer processed", "Customer data is transferred to the affiliate subject to the Standard Contractual Clauses approved by the European Commission."),
    # cycle 8 R-EXP-3 over-fire
    ("E-3 neg: end users", "Provider delivers the software for use by end users across the globe."),
    # cycle 8 R-LIAB-2 over-fire
    ("L-2 neg: cap on amounts paid by other party", "In no event shall either party's aggregate liability arising out of this agreement exceed the amounts actually paid by the other party in the preceding twelve months."),
    # cycle 8 R-COMM-5 over-fire
    ("C-5 neg: parties amend by mutual written agreement", "The parties may amend these terms at any time by mutual written agreement."),
    # cycle 8 R-EXP-2 over-fire
    ("E-2 neg: not for delivery to Cuba/Iran", "All goods are strictly not for delivery to Cuba or Iran under any circumstances."),
    # cycle 8 R-COMM-1 over-fire
    ("C-1 neg: renew unless terminated in writing", "The term shall automatically renew for successive one-year periods unless terminated in writing by either party."),
    # cycle 8 R-EXP-1 over-fire
    ("E-1 neg: exports under valid licence", "All exports shall be made under a valid export licence obtained by the exporter."),
    # cycle 9 R-COMM-4 over-fire
    ("C-4 neg: assign upon written consent", "Customer may assign this agreement to any third party upon the prior written consent of Provider."),
    # cycle 9 R-COMM-7 over-fire
    ("C-7 neg: non-refundable unless defective work", "Custom development fees are non-refundable after the work has been performed, unless the work was defective."),
    # cycle 9 R-COMM-8 over-fire
    ("C-8 neg: suspension required by law / court order", "Provider may suspend the services with immediate effect where required by law or a court order."),
    # cycle 9 R-COMM-2 over-fire
    ("C-2 neg: terminate required by law", "Company may terminate this agreement without cause where required by applicable law."),
    # cycle 9 R-COMM-3 over-fire
    ("C-3 neg: CPI-indexed fees in line with CPI", "The fees may be adjusted annually in line with the consumer price index published by the national statistics office."),
    # cycle 9 R-LIAB-3 over-fire
    ("L-3 neg: each party held harmless for own negligence", "Each party shall be held harmless by the other party for its own negligence."),
    # cycle 10 R-COMM-1 over-fire
    ("C-1 neg: auto-extend with intention not to renew", "The term shall be extended for successive one-year periods automatically unless either party gives written notice of its intention not to renew at least 60 days prior to the expiration date."),
    # cycle 10 R-LIAB-2 over-fire
    ("L-2 neg: mutual cap paid by such party", "Either party's aggregate liability shall in no event exceed the amounts paid by such party during the twelve months preceding the claim."),
    # cycle 10 R-LIAB-6 over-fire
    ("L-6 neg: liquidated damages genuine pre-estimate", "The liquidated damages sum of $10,000 represents a genuine pre-estimate of the loss likely to be suffered in the event of delay."),
    # cycle 10 R-DATA-2 over-fire
    ("D-2 neg: data stored within EEA", "All Customer data is stored on servers located within the European Economic Area (EEA)."),
    # cycle 10 R-DATA-5 over-fire
    ("D-5 neg: return or destroy within 30 days", "Following termination, Provider shall return or destroy all Customer data within thirty days."),
    # cycle 10 R-COMM-3 over-fire
    ("C-3 neg: right to adjust by mutual consent", "Customer shall have the right to adjust the fees by mutual written consent of both parties."),
    # cycle 11 R-COMM-3 over-fire
    ("C-3 neg: prices may decrease", "Prices may decrease at any time at the provider's sole discretion."),
    ("C-3 neg: no price increase for first year", "There shall be no price increase during the first year of the term."),
    ("C-3 neg: CPI-indexed increase", "Fees will increase annually in line with the consumer price index."),
    # cycle 11 R-LIAB-6 over-fire
    ("L-6 neg: penalty capped at actual loss", "Any penalty for delay shall be capped at the actual loss suffered by the buyer."),
    ("L-6 neg: reasonable estimate", "The charge represents a reasonable estimate of the anticipated loss."),
    ("L-6 neg: no penalty", "No penalty shall be payable for any delay in delivery."),
    ("L-6 neg: penalty not exceeding 5%", "The penalty for delay shall not exceed 5% of the contract value."),
    # cycle 12 R-DATA-5 over-fire (bounded retention)
    ("D-5 neg: retain for tax purposes", "Provider shall retain Customer data following termination for tax purposes as required by applicable law."),
    ("D-5 neg: retain for compliance purposes", "Following termination, Provider shall retain Customer records solely to comply with regulatory obligations."),
    # cycle 12 R-COMM-1 over-fire (opt-out / no-rollover controls)
    ("C-1 neg: renew unless notice not to renew", "This agreement shall automatically renew for successive one-year terms unless either party provides written notice not to renew at least 60 days prior to expiration."),
    ("C-1 neg: extended with 90-day opt-out", "The term shall be automatically extended for successive one-year periods unless either party gives written notice of termination at least 90 days before the expiry date."),
    ("C-1 neg: no automatic renewal", "This agreement shall not automatically renew; any renewal requires a new written agreement."),
    ("C-1 neg: continue unless notice not to renew", "This agreement shall continue in effect for successive one-year terms unless either party provides written notice not to renew at least 60 days prior to expiration."),
    ("C-1 neg: continue with 90-day opt-out", "The term shall continue for additional successive periods unless either party gives written notice of termination at least 90 days before the expiry date."),
    ("C-1 neg: deemed extended unless object", "The term shall be deemed extended automatically for additional one-year periods unless either party objects in writing at least 30 days prior to the renewal date."),
    ("C-1 neg: fixed term no rollover", "This agreement shall continue in effect for a fixed term of one year from the effective date."),
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
    # R-COMM-5 under-fire
    ("C-5 pos: update terms at any time", "Provider may update these terms at any time upon 15 days' notice."),
    # R-COMM-3 under-fire
    ("C-3 pos: prices may change", "Prices may change at any time during the term of this agreement."),
    ("C-3 pos: fees may be altered", "The fees may be altered by Provider upon 30 days' written notice."),
    # R-COMM-6 under-fire
    ("C-6 pos: $50 monthly late charge", "A late charge of $50 per month shall be assessed on any overdue invoice."),
    ("C-6 pos: carrying charge", "Unpaid balances shall bear a carrying charge of 1.5% per month until paid."),
    # R-COMM-7 under-fire
    ("C-7 pos: non-returnable and non-creditable", "All fees are non-returnable and non-creditable once services are provided."),
    # R-COMM-8 under-fire
    ("C-8 pos: discretion before verb", "Provider at its sole discretion may suspend access to the services at any time."),
    # R-LIAB-4 under-fire
    ("L-4 pos: no warranties of any kind", "Provider gives no warranties of any kind with respect to the services."),
    ("L-4 pos: makes no warranties", "Vendor makes no warranties and gives no representations regarding the software."),
    # R-LIAB-5 under-fire
    ("L-5 pos: suitable for particular purpose", "Provider makes no representations or warranties regarding the suitability of the services for a particular purpose."),
    ("L-5 pos: meet requirements", "Provider makes no warranty that the services will meet all of Customer's requirements."),
    # R-EXP-2 under-fire
    ("E-2 pos: sudan and myanmar references", "The vendor maintains distributors in Sudan and ships directly to Myanmar."),
    # cycle 7 R-COMM-2 under-fire
    ("C-2 pos: terminated for convenience", "This agreement may be terminated by Company at any time without cause and without penalty."),
    ("C-2 pos: cancelled for convenience", "The agreement may be cancelled by Provider for convenience at any time."),
    # cycle 7 R-LIAB-1 under-fire
    ("L-1 pos: liable or responsible", "Provider shall not be liable or responsible for any indirect, special or consequential damages."),
    # cycle 7 R-COMM-3 under-fire
    ("C-3 pos: prices subject to change", "Prices are subject to change at any time without prior notice."),
    # cycle 7 R-LIAB-4 under-fire
    ("L-4 pos: disclaim all warranties", "Provider expressly disclaims all warranties, express or implied."),
    # cycle 7 R-DATA-1 under-fire
    ("D-1 pos: PII collected", "The parties acknowledge that PII of customers may be collected during the provision of the services."),
    # cycle 7 R-DATA-2 under-fire
    ("D-2 pos: PII stored India", "All customer PII is stored on servers located in India."),
    # cycle 7 R-COMM-4 under-fire
    ("C-4 pos: novate no consent", "Customer may novate this agreement to any third party without the prior written consent of Provider."),
    # cycle 7 R-DATA-3 under-fire
    ("D-3 pos: marketing use", "Provider may use Customer data for marketing purposes."),
    # cycle 8 R-DATA-5 under-fire
    ("D-5 pos: retain after termination date", "After the termination date, Provider shall retain Customer data."),
    # cycle 8 R-DATA-3 under-fire
    ("D-3 pos: any reason whatsoever", "Provider may use Customer data for any reason whatsoever."),
    # cycle 8 R-DATA-5 under-fire
    ("D-5 pos: keep following expiry", "Following expiry of the agreement, the vendor may keep Customer information."),
    # cycle 8 R-COMM-2 under-fire
    ("C-2 pos: terminate without reason", "Company may terminate the agreement at any time without reason."),
    # cycle 9 R-COMM-2 under-fire
    ("C-2 pos: convenience before verb", "For its convenience and at any time, Company may terminate this agreement."),
    # cycle 9 R-COMM-3 under-fire
    ("C-3 pos: may update the service fees", "Provider may update the service fees upon 30 days' prior written notice."),
    # cycle 9 R-COMM-6 under-fire
    ("C-6 pos: carrying charge $25/month", "Unpaid balances shall bear a carrying charge of $25 per month."),
    ("C-6 pos: finance charge $25/month", "Accounts paid late shall incur a finance charge of $25 per month."),
    # cycle 9 R-LIAB-3 under-fire
    ("L-3 pos: held harmless from third-party claims", "Provider shall be held harmless from any claims by third parties arising out of Customer's use of the services."),
    # cycle 45 R-LIAB-3 under-fire ('for' connector + fault controls)
    ("L-3 pos: indemnify for any claims it may suffer", "Supplier agrees to indemnify Customer for any claims or losses it may suffer."),
    ("L-3 pos: indemnify for any claims", "Supplier shall indemnify Customer for any claims."),
    ("L-3 pos: indemnitee-fault control", "Customer shall indemnify Provider against any claims arising from Provider's own negligence."),
    ("L-3 pos: third-party own breach control", "Customer shall indemnify the Provider against all claims arising from a third party's own breach."),
    ("L-3 pos: hold harmless indemnitee-fault", "Customer shall hold Provider harmless against any claims arising from Provider's own negligence."),
    # cycle 9 R-LIAB-5 under-fire
    ("L-5 pos: availability not guaranteed", "The availability of the services at all times is not guaranteed by Provider."),
    # cycle 9 R-DATA-2 under-fire
    ("D-2 pos: accessible by employees in China", "Customer data is accessible by our employees in China."),
    # cycle 10 R-COMM-7 under-fire
    ("C-7 pos: payments final, no credits returns refunds", "All payments are final and no credits, returns, or refunds will be given once services have commenced."),
    # cycle 10 R-COMM-4 under-fire
    ("C-4 pos: transfer all rights to third party", "Customer may transfer all of its rights under this agreement to any third party without consent."),
    # cycle 10 R-COMM-3 under-fire
    ("C-3 pos: have the right to change fees", "Provider shall have the right to change the fees upon 30 days' written notice."),
    # cycle 10 R-COMM-6 under-fire
    ("C-6 pos: service charge on past due accounts", "Past due accounts are subject to a monthly service charge of 1.5%."),
    # cycle 10 R-DATA-2 under-fire
    ("D-2 pos: process through subprocessors in US", "Provider may process Customer data through subprocessors located in the United States."),
    # cycle 10 R-LIAB-1 under-fire
    ("L-1 pos: lost profits disclaimer", "Provider shall not be liable for any indirect damages, including lost profits, revenue, or business interruption."),
    # cycle 46 R-LIAB-1 under-fire (modal-less + verb-form disclaimers)
    ("L-1 pos: present is not liable for", "Provider is not liable for consequential damages of any kind."),
    ("L-1 pos: has no liability for", "Provider has no liability for consequential damages."),
    ("L-1 pos: shall have no responsibility", "The provider shall have no responsibility for consequential damages."),
    ("L-1 pos: accepts no liability", "Provider accepts no liability for any indirect damages."),
    ("L-1 pos: disclaims all liability", "Vendor disclaims all liability for consequential damages."),
    ("L-1 pos: disclaims liability for", "The licensor disclaims liability for indirect or consequential losses."),
    ("L-1 pos: excludes all liability", "Provider excludes all liability for consequential damages."),
    ("L-1 pos: shall bear no liability", "Vendor shall bear no liability for consequential damages."),
    # cycle 11 R-COMM-3 under-fire
    ("C-3 pos: prices may increase", "Prices may increase at any time upon 30 days' prior written notice to Customer."),
    ("C-3 pos: fees will increase annually", "The fees will increase annually upon 60 days' written notice."),
    # cycle 11 R-LIAB-6 under-fire
    ("L-6 pos: penalty 5% of contract value", "A penalty of 5% of the contract value shall be payable by the supplier for any delay in delivery."),
    ("L-6 pos: penalty $1,000 for any delay", "A penalty of $1,000 shall be payable by the supplier for any delay in delivery."),
    ("L-6 pos: penalty 2% of purchase price", "The supplier shall pay a penalty equal to 2% of the purchase price for each week of delay."),
    ("L-6 pos: fixed charge no tail", "A fixed charge of EUR 500 for any delay shall be paid by the supplier."),
    # cycle 12 R-COMM-1 under-fire (auto-renewal rollover variants)
    ("C-1 pos: renew automatically no opt-out", "This agreement shall renew automatically for successive one-year periods."),
    ("C-1 pos: deemed extended no opt-out", "The term shall be deemed extended automatically for additional one-year periods without further action."),
    ("C-1 pos: continue for successive terms", "This agreement shall continue in effect for successive one-year renewal terms."),
    ("C-1 pos: renewed automatically each anniversary", "The agreement will be renewed automatically on each anniversary of the effective date."),
    # cycle 12 R-DATA-5 under-fire (retention phrasing variants)
    ("D-5 pos: retain possession of data", "Following termination of this agreement, Provider may retain possession of Customer data."),
    ("D-5 pos: preserve data after termination", "Provider shall preserve Customer data after termination of this agreement."),
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
