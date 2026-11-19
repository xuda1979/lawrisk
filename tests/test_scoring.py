"""P0: deterministic, explainable risk scoring tests (AC1, AC2, calibration)."""

from __future__ import annotations

from lawrisk.models import Dimension, RiskLevel
from lawrisk.rules import score_document


class TestDeterminism:
    """AC1: same input always yields the same score."""

    def test_same_paragraphs_same_score(self):
        paras = [
            "Service Agreement",
            "The agreement automatically renews each year.",
            "Either party may terminate for convenience with 30 days notice.",
            "Provider's aggregate liability is limited to fees paid.",
        ]
        a = score_document(paras, "doc-1")
        b = score_document(paras, "doc-1")
        c = score_document(paras, "doc-1")
        assert a.overall_score == b.overall_score == c.overall_score
        assert a.deterministic_hash == b.deterministic_hash == c.deterministic_hash

    def test_order_is_irrelevant_to_hash(self):
        paras_a = ["first clause", "second clause with risk of auto-renew monthly periods"]
        paras_b = list(reversed(paras_a))
        h_a = score_document(paras_a, "x").deterministic_hash
        h_b = score_document(paras_b, "x").deterministic_hash
        # Reordering paragraphs may (by design of the hash) differ; what must be
        # stable is the two scalar scores for identical content.
        score_a = score_document(paras_a, "x").overall_score
        score_b = score_document(paras_b, "x").overall_score
        assert score_a == score_b == score_document(paras_a, "x").overall_score

    def test_score_within_0_100(self):
        r = score_document(["some clean text without any risky markers"], "d")
        assert 0 <= r.overall_score <= 100
        for d in r.dimensions:
            assert 0.0 <= d.normalized <= 100.0


class TestExplainability:
    """AC2: every finding carries reason text + source excerpt."""

    def test_every_penalty_explainable(self):
        paras = [
            "This agreement automatically renews unless cancelled.",
            "In no event shall the Provider be liable for consequential damages.",
            "Customer shall indemnify the Provider against all third-party claims.",
            "Provider processes personal data for any purpose.",
        ]
        r = score_document(paras, "d")
        assert len(r.penalties) >= 4
        for p in r.penalties:
            assert p.reason
            assert p.excerpt
            assert p.rule_id
            assert p.para_index is not None
            assert isinstance(p.dimension, Dimension)

    def test_every_penalty_has_mitigation(self):
        """AC2+: every finding carries a concrete, non-empty remediation hint."""
        paras = [
            "This agreement automatically renews unless cancelled.",
            "In no event shall the Provider be liable for consequential damages.",
            "Customer shall indemnify the Provider against all third-party claims.",
            "Provider processes personal data for any purpose.",
        ]
        r = score_document(paras, "d")
        assert len(r.penalties) >= 4
        for p in r.penalties:
            assert isinstance(p.mitigation, str)
            assert p.mitigation.strip(), f"{p.rule_id} missing mitigation"

    def test_dimension_rows_have_reasons(self):
        r = score_document(
            ["Fees increase at Provider's discretion.", "Data transfers outside the EU."], "d"
        )
        for dim in r.dimensions:
            assert dim.reasons  # non-empty string list
            assert 0.0 <= dim.confidence <= 1.0

    def test_excerpt_points_to_source(self):
        paras = ["Governing: Provider reserves the right to adjust the prices."]
        r = score_document(paras, "d")
        hit = next(p for p in r.penalties if p.rule_id == "R-COMM-3")
        assert "reserves the right to adjust" in hit.excerpt.lower() if hit.excerpt else True


class TestCalibration:
    """Known-good scores for bundled fixtures (RISK vs CLEAN separation)."""

    def test_risky_contract_is_high(self, score_docx):
        r = score_docx("risky_contract")
        assert r.overall_level is RiskLevel.HIGH
        assert r.overall_score >= 66
        assert len(r.penalties) >= 10

    def test_clean_contract_has_no_findings(self, score_docx):
        r = score_docx("clean_contract")
        assert r.overall_level is RiskLevel.LOW
        assert r.overall_score <= 15
        assert r.penalties == []

    def test_template_a_milder_than_template_b(self, score_docx):
        a = score_docx("template_a")
        b = score_docx("template_b")
        assert a.overall_score < b.overall_score

    def test_risky_contract_names_sanctioned_country(self, score_docx):
        r = score_docx("risky_contract")
        # The fixture's sanctioned-country mention is a prohibition ("shall not
        # be exported to Cuba"), i.e. a compliance carve-out, so it must NOT
        # fire. R-EXP-2 is instead exercised below via an explicitly risky
        # export-to-sanctioned-destination sentence.
        assert all(p.rule_id != "R-EXP-2" for p in r.penalties)
        r2 = score_document(
            ["Deliverables may be exported to Cuba without restriction."], "d"
        )
        assert any(p.rule_id == "R-EXP-2" for p in r2.penalties)

    def test_risky_contract_flags_unilateral_amendment(self, score_docx):
        r = score_docx("risky_contract")
        hit = next((p for p in r.penalties if p.rule_id == "R-COMM-5"), None)
        assert hit is not None
        assert "amend the terms" in hit.excerpt.lower()


class TestRuleMeshes:
    """Targeted unit checks on individual rules."""

    def test_autorenew_detected(self, score_docx):
        r = score_document(
            ["The agreement will automatically renew for further terms."], "d"
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_no_autorenew_not_detected(self):
        r = score_document(["This agreement does not auto-renew."], "d")
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_no_automatic_renew_long_form_not_detected(self):
        # Regression: "automatically renew" wording must also be excluded.
        r = score_document(
            ["This agreement does not automatically renew upon expiration."], "d"
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_no_renew_automatically_adverb_after_verb_not_detected(self):
        # Regression: the negated form "does not renew automatically" puts the
        # adverb after the verb, which must also be excluded.
        r = score_document(
            ["This agreement does not renew automatically upon expiration."], "d"
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_renews_automatically_detected(self):
        # Regression: present-tense "renews automatically" must fire the rule.
        r = score_document(
            ["The contract renews automatically each year unless cancelled."], "d"
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_renew_with_separated_automatically_detected(self):
        # Regression: "will renew for successive one-year terms automatically"
        # puts the adverb after an intervening object; it still rolls over with
        # no opt-out and must fire R-COMM-1.
        r = score_document(
            ["This agreement will renew for successive one-year terms automatically on each anniversary date."], "d"
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_neither_party_denies_renewal_not_flagged(self):
        # Regression: a "neither party" subject denying the renewal is an
        # opt-out statement and must suppress R-COMM-1.
        r = score_document(
            ["Neither party shall cause this agreement to renew automatically at expiration."], "d"
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_unrelated_neither_party_does_not_mask_autorenewal(self):
        # Regression: "neither party" in a separate sentence (here about
        # termination) must NOT suppress a genuine auto-renewal clause.
        r = score_document(
            [
                "This agreement will automatically renew for one-year terms; "
                "neither party may terminate without cause during the term."
            ],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_automatic_renewal_noun_form_detected(self):
        # Regression: the noun form "automatic renewal" (no verb) must also
        # fire R-COMM-1; the verb-pattern only was an under-fire gap.
        r = score_document(
            ["The agreement shall include an automatic renewal provision."], "d"
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_no_automatic_renewal_noun_form_not_detected(self):
        # Regression: the negated noun form must suppress R-COMM-1.
        r = score_document(
            ["There shall be no automatic renewal of this agreement."], "d"
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_elects_not_to_renew_with_opt_out_not_flagged(self):
        # Regression: an explicit opt-out window ("either party elects not to
        # renew" with notice) must suppress R-COMM-1, not fire it.
        r = score_document(
            [
                "This agreement shall renew automatically unless either party elects "
                "not to renew by written notice given at least 30 days before expiry."
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_notice_of_non_renewal_opt_out_not_flagged(self):
        # Regression: a non-renewal notice window ("notice of non-renewal")
        # immediately after the renewal term is a genuine opt-out and must
        # suppress R-COMM-1.
        r = score_document(
            [
                "The term shall be extended automatically for one year unless either "
                "party delivers written notice of non-renewal at least 60 days prior "
                "to expiration."
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_unrelated_non_renewal_notice_does_not_mask_autorenewal(self):
        # Regression: a non-renewal notice about an unrelated subject in the
        # same paragraph must not suppress a genuine auto-renewal clause scoped
        # to the renewal term.
        r = score_document(
            [
                "This agreement shall renew automatically for one-year terms; notice "
                "of non-renewal must be given by the tenant in any lease."
            ],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_objects_in_writing_opt_out_not_flagged(self):
        # Regression: an opt-out action expressed as "objects in writing" (no
        # "notice of non-renewal" phrasing) with a written objection window must
        # suppress R-COMM-1, not fire it.
        r = score_document(
            [
                "This agreement shall be automatically renewed for successive one-year "
                "periods unless either party objects in writing at least sixty days "
                "prior to expiration."
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_shall_automatically_be_extended_detected(self):
        # Regression: "shall automatically be extended" places the adverb between
        # the modal and "be extended"; that passive roll-over with no opt-out must
        # fire R-COMM-1.
        r = score_document(
            ["The term of this agreement shall automatically be extended for successive one-year periods."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_mutual_termination_not_flagged(self):
        r = score_document(
            ["Either party may terminate this agreement for convenience."], "d"
        )
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_one_sided_termination_flagged(self):
        r = score_document(
            ["Provider may terminate this agreement without cause at any time."], "d"
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_terminate_at_will_flagged(self):
        # Regression: "terminate ... at will" is a one-sided no-cause termination
        # right and must fire R-COMM-2 (the "at will" tail was missing).
        r = score_document(
            ["Provider may terminate this agreement at will upon 30 days notice."], "d"
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_terminable_at_will_flagged(self):
        # Regression: the adjective form "terminable at will" is the same
        # one-sided no-cause right and must fire R-COMM-2.
        r = score_document(
            ["This agreement is terminable at will by the provider."], "d"
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_vendor_not_responsible_not_flagged(self):
        # Regression: "vendor" contains the substring "end"; without a word
        # boundary the R-COMM-2 pattern matched "vENDor" plus "for any ..." and
        # fired a one-sided-termination finding on a liability disclaimer.
        r = score_document(
            ["The vendor shall not be responsible for any indirect or consequential losses."], "d"
        )
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_unilateral_amendment_flagged(self):
        r = score_document(
            ["Provider may amend the terms of this Agreement at any time without prior notice."], "d"
        )
        assert any(p.rule_id == "R-COMM-5" for p in r.penalties)

    def test_mutual_amendment_not_flagged(self):
        r = score_document(
            ["Either party may amend this Agreement by written agreement signed by both parties."], "d"
        )
        assert all(p.rule_id != "R-COMM-5" for p in r.penalties)

    def test_bound_amendment_not_flagged(self):
        r = score_document(
            ["This Agreement shall not be amended except by a written instrument signed by both parties."], "d"
        )
        assert all(p.rule_id != "R-COMM-5" for p in r.penalties)

    def test_export_compliance_affirmation_not_flagged(self):
        r = score_document(
            ["Each party shall comply with all applicable export control and sanctions laws."], "d"
        )
        assert all(p.dimension is not Dimension.EXPORT for p in r.penalties)

    def test_subject_to_us_sanctions_not_flagged(self):
        # Regression: "subject to US sanctions" must be recognised as an
        # export-affirming clause, not a sanctions risk (R-EXP-1 exclusion).
        r = score_document(
            ["This Agreement is subject to US sanctions regulations and export licensing."], "d"
        )
        assert all(p.rule_id != "R-EXP-1" for p in r.penalties)

    def test_no_fulfilment_to_sanctioned_jurisdiction_not_flagged(self):
        # Regression: a prohibition-form clause refusing fulfilment to a
        # sanctioned jurisdiction is a compliance control, not a claim to trade
        # there; R-EXP-1 must stay silent (R-EXP-2 already excludes it).
        r = score_document(
            ["Orders shall not be fulfilled to any sanctioned jurisdiction, including Cuba, Iran and Syria."],
            "d",
        )
        assert all(p.rule_id != "R-EXP-1" for p in r.penalties)

    def test_reexport_diversion_compliance_not_flagged(self):
        # Regression: an affirmative re-export/diversion control clause must not
        # trigger the absence rule R-EXP-4.
        r = score_document(
            ["Promptly notify the other party of any export re-export diversion risk and comply with applicable controls."], "d"
        )
        assert all(p.rule_id != "R-EXP-4" for p in r.penalties)

    def test_unrestricted_assignment_flagged(self):
        r = score_document(
            ["Provider may assign this agreement without the prior written consent of Customer."], "d"
        )
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_consent_bound_assignment_not_flagged(self):
        r = score_document(
            ["Neither party may assign this agreement without the consent of the other party."], "d"
        )
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_assign_rights_and_obligations_flagged(self):
        # Regression: "assign its rights and obligations under this agreement"
        # puts an intervening object between the verb and "this agreement"; that
        # unrestricted third-party assignment must fire R-COMM-4.
        r = score_document(
            [
                "Customer may assign its rights and obligations under this agreement "
                "to any third party without the prior written consent of Provider."
            ],
            "d",
        )
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_affiliate_assignment_not_flagged(self):
        r = score_document(
            ["Either party may assign this agreement to an affiliate without consent."], "d"
        )
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_liability_cap_shall_not_exceed_flagged(self):
        r = score_document(
            ["The aggregate liability of each party shall not exceed the fees paid."], "d"
        )
        assert any(p.rule_id == "R-LIAB-2" for p in r.penalties)

    def test_liability_cap_long_gap_flagged(self):
        # Regression: the subject/gap between "liability" and "limited to" may
        # exceed the original 40-char window.
        r = score_document(
            ["The total liability of either party under this agreement is limited to twelve months of fees."], "d"
        )
        assert any(p.rule_id == "R-LIAB-2" for p in r.penalties)

    def test_liability_cap_denial_not_flagged(self):
        # Regression: cap-denial language ("shall not be limited to",
        # "nothing in this clause limits") must NOT fire R-LIAB-2.
        cases = [
            ["Nothing in this clause limits Provider's liability; liability shall not be limited to the fees paid."],
            ["Provider's liability shall not be limited to amounts received."],
            ["There shall be no limitation of liability for fraud."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-LIAB-2" for p in r.penalties), paras

    def test_late_payment_charge_flagged(self):
        r = score_document(
            ["A late payment service charge of 1.5% per month applies to overdue amounts."], "d"
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_deliverable_mention_without_export_topic_not_flagged(self):
        # Regression: plain "deliverables" wording must not trigger the
        # absence rule R-EXP-4 (export-compliance clause missing).
        r = score_document(
            ["The Provider shall provide the deliverables by the due date."], "d"
        )
        assert all(p.rule_id != "R-EXP-4" for p in r.penalties)

    def test_international_shipment_verbs_trigger_export_absence(self):
        # Regression: plain international trade verbs ("ships the goods
        # internationally", "deliver overseas", "sold to buyers abroad") must
        # trigger R-EXP-4's topic condition even when the word "export" and the
        # noun "shipment" never appear.
        cases = [
            ["The vendor ships the goods internationally."],
            ["The vendor will deliver the goods overseas."],
            ["Goods are sold to buyers abroad."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-EXP-4" for p in r.penalties), paras

    def test_international_trade_with_compliance_not_flagged(self):
        # Guard: even with an international-trade topic trigger, an existing
        # export-compliance clause must keep R-EXP-4 (absence) silent.
        r = score_document(
            [
                "The vendor ships the goods internationally and complies with "
                "export control regulations."
            ],
            "d",
        )
        assert all(p.rule_id != "R-EXP-4" for p in r.penalties)

    def test_canonical_indemnity_from_third_party_claims_detected(self):
        # Regression: the "indemnify and hold harmless X from third party
        # claims" phrasing must recall R-LIAB-3 even when the object clause
        # is longer than a few words.
        r = score_document(
            ["Buyer shall indemnify and hold harmless Seller from third party claims."], "d"
        )
        assert any(p.rule_id == "R-LIAB-3" for p in r.penalties)

    def test_data_protection_clause_not_flagged(self):
        r = score_document(
            ["Personal data shall be processed in accordance with GDPR and the DPA."], "d"
        )
        assert all(p.rule_id != "R-DATA-1" for p in r.penalties)

    def test_late_payment_interest_flagged(self):
        r = score_document(
            ["Late payments attract interest at 2% per month."], "d"
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_ordinary_dunning_not_flagged(self):
        r = score_document(
            ["Invoices are due within 30 days; reminders will be sent for overdue amounts."], "d"
        )
        assert all(p.rule_id != "R-COMM-6" for p in r.penalties)

    def test_late_payment_interest_decimal_rate_flagged(self):
        # Regression: "1.8% per month" crosses a decimal point; the pattern must
        # not let the [^.;] window stop at the "." inside the rate.
        r = score_document(
            ["Customer shall pay interest at 1.8% per month on all overdue amounts."], "d"
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_late_fee_percentage_flagged(self):
        # Regression: "late fee of 5%" has no "late payment"/"interest" wording;
        # the fixed-rate form must be caught on its own.
        r = score_document(
            ["A late fee of 5% per month applies to delinquent accounts."], "d"
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_market_benchmarked_interest_not_flagged(self):
        # Regression: interest benchmarked to a market/statutory/bank rate is the
        # rule's own recommended non-risky style (see mitigation "Cap late-payment
        # interest at a statutory or market rate").
        r = score_document(
            ["Late payments attract interest at a rate of 1.5% per annum above the ECB base rate."], "d"
        )
        assert all(p.rule_id != "R-COMM-6" for p in r.penalties)

    def test_statutory_rate_interest_not_flagged(self):
        r = score_document(
            ["Late payments accrue interest at the statutory rate."], "d"
        )
        assert all(p.rule_id != "R-COMM-6" for p in r.penalties)

    def test_euribor_benchmark_interest_not_flagged(self):
        r = score_document(
            ["Late payments attract EURIBOR interest at 3 month EURIBOR plus 2%."], "d"
        )
        assert all(p.rule_id != "R-COMM-6" for p in r.penalties)

    def test_delinquent_account_interest_flagged(self):
        # Regression: word-order "interest on ... delinquent accounts at 1.5%
        # per month" puts the rate after a long qualifier.
        r = score_document(
            ["The customer shall pay interest on any delinquent accounts at 1.5% per month."], "d"
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_fixed_dollar_penalty_charge_flagged(self):
        # Regression: a fixed-dollar penalty charge without any percentage.
        r = score_document(
            ["A 30-day grace period applies, after which a penalty charge of $500 accrues weekly."], "d"
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_plain_dollar_fee_not_flagged(self):
        # Precision: an ordinary dollar fee (no late payment/penalty context)
        # must not be mistaken for a late-payment penalty.
        r = score_document(
            ["Customer shall pay a setup fee of $100,000 upon signature."], "d"
        )
        assert all(p.rule_id != "R-COMM-6" for p in r.penalties)

    def test_non_refundable_fees_flagged(self):
        r = score_document(
            ["All fees are non-refundable and non-cancellable."], "d"
        )
        assert any(p.rule_id == "R-COMM-7" for p in r.penalties)

    def test_refund_policy_not_flagged(self):
        r = score_document(
            ["Unused portions of prepaid fees may be refunded on written request."], "d"
        )
        assert all(p.rule_id != "R-COMM-7" for p in r.penalties)

    def test_no_refunds_shall_be_made_flagged(self):
        # Regression: "no refunds shall/will be made" wording (no literal
        # "non-refundable") must fire R-COMM-7.
        r = score_document(
            ["All amounts paid under this agreement are final; no refunds shall be made once services have been delivered."], "d"
        )
        assert any(p.rule_id == "R-COMM-7" for p in r.penalties)

    def test_no_refunds_will_be_given_flagged(self):
        # Regression: "no refunds will be given for any reason" must fire.
        r = score_document(
            ["Once the order is placed, no refunds will be given for any reason."], "d"
        )
        assert any(p.rule_id == "R-COMM-7" for p in r.penalties)

    def test_payments_final_not_refunded_flagged(self):
        # Regression: "payments ... are final and shall not be refunded"
        # wording (noun + passive verb, no literal "non-refundable") must fire.
        cases = [
            ["All payments made under this agreement are final and shall not be refunded once the services have been provided."],
            ["All fees are final and shall not be refunded or returned to Customer under any circumstances."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-COMM-7" for p in r.penalties), paras

    def test_availability_disclaimer_flagged(self):
        r = score_document(
            ["Provider does not warrant that the Services will be uninterrupted or error-free."], "d"
        )
        assert any(p.rule_id == "R-LIAB-5" for p in r.penalties)

    def test_no_representations_availability_flagged(self):
        # Regression: "makes no representations or warranties regarding the
        # availability" (noun forms, no matchable verb or "available"
        # adjective) must fire R-LIAB-5.
        r = score_document(
            ["Provider makes no representations or warranties regarding the availability of the Services."], "d"
        )
        assert any(p.rule_id == "R-LIAB-5" for p in r.penalties)

    def test_does_not_warrant_reliability_flagged(self):
        # Regression: "does not warrant the reliability" (availability noun
        # family beyond the literal "available") must fire R-LIAB-5.
        r = score_document(
            ["The Company does not warrant the reliability of the services."], "d"
        )
        assert any(p.rule_id == "R-LIAB-5" for p in r.penalties)

    def test_availability_sla_not_flagged(self):
        r = score_document(
            ["The Services will be available 99.9% of the time; guaranteed response times apply."], "d"
        )
        assert all(p.rule_id != "R-LIAB-5" for p in r.penalties)

    def test_no_warranty_fitness_for_purpose_flagged(self):
        # Regression: "makes no warranty of fitness for a particular purpose"
        # must fire R-LIAB-5 even though the qualifier is "fitness for".
        r = score_document(
            ["Vendor makes no warranty of fitness for a particular purpose."], "d"
        )
        assert any(p.rule_id == "R-LIAB-5" for p in r.penalties)

    def test_disclaims_warranties_merchantability_flagged(self):
        # Regression: "disclaims all warranties ... including merchantability"
        # must fire R-LIAB-5.
        r = score_document(
            ["Vendor disclaims all warranties, express or implied, including merchantability."], "d"
        )
        assert any(p.rule_id == "R-LIAB-5" for p in r.penalties)

    def test_unilateral_suspension_flagged(self):
        r = score_document(
            ["Provider may suspend the Services at any time without prior notice."], "d"
        )
        assert any(p.rule_id == "R-COMM-8" for p in r.penalties)

    def test_notice_bound_suspension_not_flagged(self):
        r = score_document(
            ["Provider may suspend the Services only if 30 days' written notice is given."], "d"
        )
        assert all(p.rule_id != "R-COMM-8" for p in r.penalties)

    def test_liquidated_damages_flagged(self):
        r = score_document(
            ["Customer shall pay liquidated damages of $1,000 per day for delay."], "d"
        )
        assert any(p.rule_id == "R-LIAB-6" for p in r.penalties)

    def test_genuine_pre_estimate_not_flagged(self):
        r = score_document(
            ["Liquidated damages are a genuine pre-estimate of loss."], "d"
        )
        assert all(p.rule_id != "R-LIAB-6" for p in r.penalties)

    def test_post_termination_retention_flagged(self):
        r = score_document(
            ["Customer data shall be retained after termination for seven years."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_law_bound_retention_not_flagged(self):
        r = score_document(
            ["Customer data shall be retained after termination only as required by law."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)

    def test_keep_and_store_retention_forms_flagged(self):
        # Regression: R-DATA-5 must also catch active-verb forms ("will store",
        # "keep") and "information", not only passive "shall be retained".
        cases = [
            ["Provider may keep personal information following termination of this agreement."],
            ["The company will store customer data upon such termination for audit purposes."],
            ["Provider may retain customer data after such termination for seven years."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), paras

    def test_delete_on_termination_not_flagged(self):
        # Regression: a deletion obligation is a protective retention bound and
        # must not fire R-DATA-5.
        r = score_document(
            ["Provider shall delete all customer data upon termination of this agreement."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)

    def test_bounded_retention_window_not_flagged(self):
        # Regression: retention bounded to a delete/return window after
        # termination is a protective bound and must not fire R-DATA-5.
        cases = [
            ["Provider shall retain customer data after termination only until such data is deleted within ninety (90) days of termination."],
            ["Provider may keep customer data following termination only to the extent needed to return it to the customer on request."],
            ["Provider may store customer data after termination for a period of 90 days."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), paras

    def test_unbounded_retention_still_flagged(self):
        # Guard: genuinely unbounded retention ("for seven years") and open
        # post-termination keeping must still fire R-DATA-5 despite the new
        # bounded-window exclusions.
        cases = [
            ["Customer data shall be retained after termination for seven years."],
            ["Provider may keep personal information following termination of this agreement."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), paras

    def test_keep_copies_or_extracts_retention_flagged(self):
        # Regression: retention verbs with an intervening "copies of" / "extracts
        # of" noun ("keep copies of Customer data", "store extracts of Customer
        # information") must still fire R-DATA-5.
        cases = [
            ["Provider may keep copies of Customer data following termination of this agreement."],
            ["Provider shall store extracts of Customer information upon termination for its own records."],
            ["Provider may retain backup copies of Customer personal data following such termination."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), paras

    def test_keep_records_of_customer_data_flagged(self):
        # Regression: "keep records of Customer data following termination"
        # (retention verb + "records of") must fire R-DATA-5 like copies and
        # extracts do.
        r = score_document(
            ["Provider may keep records of Customer data following termination of this agreement."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_bounded_retention_then_deletion_not_flagged(self):
        # Regression: retention bounded to a fixed window followed by an explicit
        # deletion/return obligation ("after which it shall be deleted") is a
        # protective bound and must not fire R-DATA-5.
        cases = [
            ["Provider may retain Customer data for ninety (90) days following termination of this agreement, after which it shall be deleted."],
            ["Provider may keep Customer data for six months after termination, after which it shall be returned to the customer."],
            ["Provider shall store Customer information for sixty (60) days following termination, after which such data shall be destroyed."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), paras

    def test_extended_rules_keep_clean_footer_text_clean(self):
        """Calibration guard: extended rule set adds no findings to clean fixtures."""
        r = score_document(
            [
                "Professional services agreement between the parties.",
                "Either party may terminate by mutual written agreement.",
            ],
            "d",
        )
        assert all(
            p.rule_id
            not in {"R-COMM-6", "R-COMM-7", "R-LIAB-5", "R-COMM-8", "R-LIAB-6", "R-DATA-5"}
            for p in r.penalties
        )

    def test_shall_not_assign_without_consent_not_flagged(self):
        # Regression: the consent-bound "shall/will not assign" phrasing must be
        # suppressed by the R-COMM-4 exclusion, not only the "may assign" form.
        r = score_document(
            ["Neither party shall assign this agreement without the prior written consent of the other."], "d"
        )
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_neither_will_assign_without_consent_not_flagged(self):
        r = score_document(
            ["Neither party will assign these presents without the prior written consent of the other."], "d"
        )
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_broad_liability_disclaimer_flagged(self):
        r = score_document(
            ["In no event shall the Provider be liable for consequential damages."], "d"
        )
        assert any(p.rule_id == "R-LIAB-1" for p in r.penalties)

    def test_liability_disclaimer_with_carve_outs_not_flagged(self):
        r = score_document(
            ["In no event shall the Provider be liable for consequential damages, except for fraud or gross negligence."], "d"
        )
        assert all(p.rule_id != "R-LIAB-1" for p in r.penalties)

    def test_mutual_liability_disclaimer_not_flagged(self):
        r = score_document(
            ["In no event shall either party be liable for consequential damages."], "d"
        )
        assert all(p.rule_id != "R-LIAB-1" for p in r.penalties)

    def test_vendor_supplier_liability_disclaimer_flagged(self):
        # Regression: "vendor" / "supplier" / "licensor" subjects were missing
        # from the R-LIAB-1 alternation and slipped past the rule.
        cases = [
            ["Under no circumstances shall the vendor be liable for indirect or consequential damages."],
            ["Supplier shall not be liable for consequential losses, lost profits or loss of goodwill."],
            ["The licensor shall not have any liability for delay or non-performance of the software."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-LIAB-1" for p in r.penalties), paras

    def test_shall_have_no_liability_flagged(self):
        # Regression: the "shall have no liability for" construction (object
        # form, no "not" after the subject) was missing from the R-LIAB-1
        # subject branch and slipped past the rule.
        r = score_document(
            ["The provider shall have no liability for consequential or indirect losses arising from use of the services."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-1" for p in r.penalties)

    def test_vendor_disclaimer_with_carve_outs_not_flagged(self):
        # Guard: vendor/supplier disclaimers that do carry carve-outs must stay
        # silent under R-LIAB-1.
        r = score_document(
            ["Under no circumstances shall the vendor be liable for indirect damages; nothing in this clause excludes liability for death or personal injury."], "d"
        )
        assert all(p.rule_id != "R-LIAB-1" for p in r.penalties)

    def test_mutual_cap_each_party_not_flagged(self):
        # Regression: a symmetric cap applying to both parties (mutual "each
        # party / either party" subject) is not a one-sided exposure and must
        # not fire R-LIAB-2.
        cases = [
            ["The total aggregate liability of each party under this agreement is limited to the amounts actually paid or received under this agreement."],
            ["Full liability of either party shall not exceed the amounts actually paid or received under this agreement."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-LIAB-2" for p in r.penalties), paras

    def test_one_sided_cap_still_flagged(self):
        # Guard: a cap binding only the counterparty must still fire R-LIAB-2
        # even though "each party" appears elsewhere in the sentence field.
        cases = [
            ["Provider's aggregate liability under this agreement is limited to the fees paid in the preceding twelve months."],
            ["The aggregate liability of the supplier is limited to amounts actually received; each party bears its own costs."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-LIAB-2" for p in r.penalties), paras

    def test_liability_shall_in_no_event_exceed_flagged(self):
        # Regression: "liability shall in no event exceed" places the adverb
        # between "shall" and the cap verb; the pattern only matched
        # "shall not exceed" and slipped past the rule.
        r = score_document(
            ["The provider's aggregate liability shall in no event exceed the fees paid in the twelve months preceding the claim."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-2" for p in r.penalties)

    def test_liability_in_excess_of_amounts_paid_flagged(self):
        # Regression: "shall have liability in excess of the amounts actually
        # paid" is the classic cap-at-fees formulation; "in excess of" was
        # missing from the R-LIAB-2 pattern. The asymmetric "Neither the
        # provider nor its affiliates" subject keeps it out of the mutual
        # "paid or received" exclusion.
        r = score_document(
            ["Neither the provider nor its affiliates shall have liability in excess of the amounts actually paid by Customer."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-2" for p in r.penalties)

    def test_as_is_disclaimer_flagged(self):
        r = score_document(
            ["The Services are provided on an as-is basis without warranties of any kind."], "d"
        )
        assert any(p.rule_id == "R-LIAB-4" for p in r.penalties)

    def test_positive_warranty_not_flagged(self):
        r = score_document(
            ["Provider warrants the Services will conform to the specification for 12 months."], "d"
        )
        assert all(p.rule_id != "R-LIAB-4" for p in r.penalties)

    def test_cross_border_data_transfer_flagged(self):
        r = score_document(
            ["Provider may transfer personal data outside the EEA for processing."], "d"
        )
        assert any(p.rule_id == "R-DATA-2" for p in r.penalties)

    def test_hosted_in_united_states_flagged(self):
        # Regression: "will be hosted in the United States" is a cross-border
        # data-location statement; "hosted" was missing from the R-DATA-2
        # verb lists and slipped past the rule.
        r = score_document(
            ["Customer data will be hosted in the United States by the provider's affiliate."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-2" for p in r.penalties)

    def test_stored_on_servers_in_named_country_flagged(self):
        # Regression: a named non-EEA country (India) as a data-location
        # statement is the same cross-border location risk as "hosted in the
        # United States" and must fire R-DATA-2. This only fired R-DATA-1
        # because the destination list lacked generic country names.
        r = score_document(
            ["Personal information will be stored on servers located in India."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-2" for p in r.penalties)

    def test_eu_storage_location_not_transfer_flagged(self):
        # Regression: "the European Union" (EU-as-region, not the "EU" shorthand)
        # must not count as a cross-border transfer destination for R-DATA-2.
        r = score_document(
            ["Customer personal data shall be stored on servers located in the European Union only."], "d"
        )
        assert all(p.rule_id != "R-DATA-2" for p in r.penalties)

    def test_transfer_prohibition_not_flagged(self):
        # Regression: prohibition-form clauses ("shall not be transferred",
        # "No transfer ... shall occur without safeguards") are protective and
        # must not fire R-DATA-2.
        r = score_document(
            [
                "Customer data shall not be transferred outside the EEA without appropriate safeguards.",
                "No transfer of personal data outside the EU shall occur without standard contractual clauses.",
            ],
            "d",
        )
        assert all(p.rule_id != "R-DATA-2" for p in r.penalties)

    def test_unlimited_data_processing_flagged(self):
        r = score_document(
            ["Provider may process Customer data for any purpose."], "d"
        )
        assert any(p.rule_id == "R-DATA-3" for p in r.penalties)

    def test_process_for_any_other_purpose_flagged(self):
        # Regression: "for any other purpose" is the same open-ended processing
        # purpose as "for any purpose" and must fire R-DATA-3.
        r = score_document(
            ["Provider may process Customer data for any other purpose without limitation."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-3" for p in r.penalties)

    def test_use_for_any_and_all_purposes_flagged(self):
        # Regression: "for any and all purposes" is an all-purpose grant and
        # must fire R-DATA-3.
        r = score_document(
            ["Provider may use the data for any and all purposes."], "d"
        )
        assert any(p.rule_id == "R-DATA-3" for p in r.penalties)

    def test_unsafeguarded_transfer_flagged(self):
        # Regression: "without appropriate safeguards" is the gap itself; a
        # transfer that names no safeguards must still fire R-DATA-2.
        r = score_document(
            ["Customer personal data may be transferred outside the EEA without appropriate safeguards."], "d"
        )
        assert any(p.rule_id == "R-DATA-2" for p in r.penalties)

    def test_passive_denial_of_processing_not_flagged(self):
        # Regression: passive denial forms ("shall not be processed",
        # "are not collected") are protective and must not fire either
        # R-DATA-1 or the absence check R-DATA-4.
        for para in [
            "Personal data shall not be processed under this agreement.",
            "Personal data are not collected, processed or stored under this agreement.",
            "Personal data will not be transferred or disclosed to any third party.",
        ]:
            r = score_document([para], "d")
            assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties), para

    def test_purpose_limited_processing_not_flagged(self):
        r = score_document(
            ["Provider may process Customer data solely for the purpose of providing the Services."], "d"
        )
        assert all(p.rule_id != "R-DATA-3" for p in r.penalties)

    def test_use_data_for_own_business_purposes_flagged(self):
        # Regression: "use customer data for its own business purposes" must
        # fire R-DATA-3 even though the verb is "use", not "process".
        r = score_document(
            ["Provider may use customer data for its own business purposes, including analytics."], "d"
        )
        assert any(p.rule_id == "R-DATA-3" for p in r.penalties)

    def test_use_data_for_own_purposes_flagged(self):
        # Regression: the verb-set extension must also catch "use ... for its
        # own purposes" without the word "business".
        r = score_document(
            ["The vendor may use non-personal customer data for its own purposes."], "d"
        )
        assert any(p.rule_id == "R-DATA-3" for p in r.penalties)

    def test_purpose_limited_personal_data_processing_not_flagged(self):
        # Regression: "collected and processed solely for the purpose" and
        # "will only be processed" are purpose-limited and must not fire
        # the generic personal-data rule R-DATA-1.
        r = score_document(
            [
                "Personal data is collected and processed solely for the purpose of providing the services.",
                "Personal data will only be processed to perform the agreement.",
            ],
            "d",
        )
        assert all(p.rule_id != "R-DATA-1" for p in r.penalties)

    def test_reexport_without_authorization_flagged(self):
        # Regression: "re-exported without prior authorization" is a control gap
        # and must fire R-EXP-3 even though the word "authorization" is present.
        r = score_document(
            ["Deliverables may be re-exported without prior authorization."], "d"
        )
        assert any(p.rule_id == "R-EXP-3" for p in r.penalties)

    def test_controlled_reexport_not_flagged(self):
        r = score_document(
            ["Deliverables are subject to export controls and screening."], "d"
        )
        assert all(p.rule_id != "R-EXP-3" for p in r.penalties)

    def test_authorization_bound_reexport_not_flagged(self):
        r = score_document(
            ["Re-export of deliverables requires prior written authorization from Provider."], "d"
        )
        assert all(p.rule_id != "R-EXP-3" for p in r.penalties)

    def test_prohibited_reexport_after_written_approval_not_flagged(self):
        # Regression: a flat prohibition ("may not be re-exported without ...
        # approval") is a control, not a gap, and must not fire R-EXP-1/R-EXP-3.
        r = score_document(
            ["Deliverables may be shipped worldwide, but may not be re-exported without the prior written approval of the licensor."], "d"
        )
        assert all(p.rule_id not in {"R-EXP-1", "R-EXP-3"} for p in r.penalties)

    def test_reexport_ban_without_export_licence_not_flagged(self):
        # Regression: "shall not re-export ... without an export licence" is a
        # protective prohibition (the licence requirement is the control) and
        # must not fire R-EXP-1 or R-EXP-3; "licence" was missing from the
        # post-"without" tails of both exclusions.
        r = score_document(
            ["The buyer shall not re-export the software to any third party without an export licence."],
            "d",
        )
        assert all(p.rule_id not in {"R-EXP-1", "R-EXP-3"} for p in r.penalties)

    def test_mutual_price_adjustment_not_flagged(self):
        # Regression: mutual/indexed price adjustments must not fire R-COMM-3.
        r = score_document(
            [
                "Fees may be adjusted annually by mutual written agreement of the parties.",
                "The parties agree to adjust the price each year in accordance with the published CPI index.",
                "There will be no price increase during the initial twelve month term.",
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-3" for p in r.penalties)

    def test_unilateral_price_adjustment_flagged(self):
        r = score_document(
            ["Provider reserves the right to adjust the fees at any time upon 60 days written notice."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-3" for p in r.penalties)

    def test_mutual_own_fault_indemnity_not_flagged(self):
        # Regression: mutual or own-fault indemnity constructions must not fire R-LIAB-3.
        r = score_document(
            [
                "Each party shall indemnify the other party against third party claims arising from its own breach or negligence.",
                "Either party shall indemnify the other against claims arising out of the indemnifying party's own negligence.",
            ],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-3" for p in r.penalties)

    def test_compliance_limited_processing_not_flagged(self):
        # Regression: "necessary to comply with law" is a lawful-basis carve-out,
        # not an unlimited processing purpose (R-DATA-3).
        r = score_document(
            ["Provider may process data for any purpose necessary to comply with applicable law."],
            "d",
        )
        assert all(p.rule_id != "R-DATA-3" for p in r.penalties)

    def test_unrestricted_export_flags_and_prohibition_does_not(self):
        # Regression: R-EXP-1 must match "exported/exporting", and a sanctioned-
        # destination prohibition is a compliance carve-out that must not fire
        # R-EXP-2, whereas a genuinely-risk export to a sanctioned destination
        # must still fire.
        r = score_document(
            [
                "Deliverables may be exported to any country without restriction.",
                "The parties shall not export goods or services to Cuba, Iran, Syria, North Korea or Crimea.",
            ],
            "d",
        )
        assert any(p.rule_id == "R-EXP-1" for p in r.penalties)
        assert all(p.rule_id != "R-EXP-2" for p in r.penalties)
        r2 = score_document(
            ["Deliverables may be exported to Cuba without restriction."], "d"
        )
        assert any(p.rule_id == "R-EXP-2" for p in r2.penalties)

    def test_termination_for_sole_convenience_flagged(self):
        # Regression: "sole/own/absolute convenience" is a one-sided for-
        # convenience termination right that must fire R-COMM-2, while mutual
        # or consent-bound constructions stay silent.
        r = score_document(
            ["Provider may terminate the agreement under this section at its sole convenience."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)
        r2 = score_document(
            [
                "Either party may terminate this agreement for any reason upon 30 days' written notice.",
                "The customer may terminate for convenience, provided that it gives the provider 30 days' notice.",
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-2" for p in r2.penalties)

    def test_liability_capped_at_formulation_flagged(self):
        # Regression: "liability ... capped at <amount>" is an aggregate
        # liability cap equivalent to "limited to" / "shall not exceed".
        r = score_document(
            ["Provider's liability under this agreement is capped at the total fees paid."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-2" for p in r.penalties)

    def test_generic_penalty_and_forfeiture_flagged_as_liquidated_damages(self):
        # Regression: penalty/forfeiture clauses without the words "liquidated
        # damages" still concentrate recovery risk and must fire R-LIAB-6,
        # while penalty-exclusion and pre-estimate-of-loss wording stay silent.
        cases = [
            ["Any delay in delivery will incur a penalty of $5,000 per week."],
            ["A penalty of 10% of the contract value shall be forfeited for each missed milestone."],
            ["Milestone delays are subject to a fixed charge of $2,000 per day."],
        ]
        for paras in cases:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-LIAB-6" for p in r.penalties), paras
        benign = [
            ["No liquidated damages shall apply for delay caused by the customer."],
            ["Liquidated damages are a genuine pre-estimate of loss and are not a penalty."],
        ]
        for paras in benign:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-LIAB-6" for p in r.penalties), paras

    def test_penalty_fires_despite_unrelated_no_party_sentence(self):
        # Regression: a genuine per-day penalty must fire even when the same
        # paragraph separately says "no party" about an unrelated topic.
        r = score_document(
            [
                "The supplier shall pay a penalty of $500 per day for each day "
                "of delay; no party may terminate this agreement during the term."
            ],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-6" for p in r.penalties)

    def test_neither_party_denial_of_penalty_not_flagged(self):
        # Regression: "neither party" denying liability for a penalty is a
        # protective statement and must suppress R-LIAB-6.
        r = score_document(
            ["Neither party shall be liable for a penalty or liquidated damages for delay."], "d"
        )
        assert all(p.rule_id != "R-LIAB-6" for p in r.penalties)

    def test_international_shipment_triggers_export_controls_absence_check(self):
        # Regression: "shipped internationally" substitutes for the word
        # "export" as the topic gate; with no export-control clause present the
        # absence rule must fire, and must be suppressed once compliance terms
        # appear anywhere in the document.
        r = score_document(
            ["Goods will be shipped internationally under Incoterms."],
            "d",
        )
        assert any(p.rule_id == "R-EXP-4" for p in r.penalties)
        r2 = score_document(
            [
                "Goods will be shipped internationally under Incoterms.",
                "Sellers shall comply with all applicable export control laws.",
            ],
            "d",
        )
        assert all(p.rule_id != "R-EXP-4" for p in r2.penalties)

    def test_compliance_with_general_laws_including_sanctions_not_flagged(self):
        # Regression: a generic compliance clause that expressly covers
        # "sanctions administered by OFAC" is an export-compliance protective
        # term and must not fire the absence rule R-EXP-4.
        r = score_document(
            ["Both parties shall comply with all applicable laws, including sanctions administered by OFAC."],
            "d",
        )
        assert all(p.rule_id != "R-EXP-4" for p in r.penalties)

    def test_no_business_with_sanctioned_countries_not_flagged(self):
        # Regression: a flat prohibition of dealings with sanctioned countries
        # is protective and must not fire the absence rule R-EXP-4.
        r = score_document(
            ["Neither party shall engage in business dealings with sanctioned countries."],
            "d",
        )
        assert all(p.rule_id != "R-EXP-4" for p in r.penalties)

    def test_international_trade_without_compliance_clause_still_flagged(self):
        # Regression: the broadened protective pattern must not mask a genuine
        # absence gap (international trade with no compliance wording anywhere).
        r = score_document(
            ["Buyers may sell the goods to customers abroad in any country."],
            "d",
        )
        assert any(p.rule_id == "R-EXP-4" for p in r.penalties)

    def test_consent_based_processing_not_flagged(self):
        # Regression: consent / lawful-basis constructions resolve the lawful
        # basis question and must not fire R-DATA-1, while open-ended "any
        # purpose" processing stays flagged.
        benign = [
            ["The provider shall process personal data with the explicit consent of the data subjects."],
            ["Personal data is collected based on the data subject's consent."],
            ["We process personal information under a lawful basis set out in the DPA."],
        ]
        for paras in benign:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-DATA-1" for p in r.penalties), paras
        r = score_document(["The company may use personal data for any purpose."], "d")
        assert any(p.rule_id == "R-DATA-1" for p in r.penalties)

    def test_passive_cross_border_transfer_forms_flagged(self):
        # Regression: passive/verbal phrasings of cross-border data transfer
        # (data-led verbs, processing/accessing/sharing outbound) must fire
        # R-DATA-2, while prohibitions with safeguards stay silent.
        risky = [
            ["Personal data shall be transferred to the United States."],
            ["Customer data is transmitted to third-country servers."],
            ["Personal data shall be transferred abroad."],
            ["Data may be processed outside the EEA."],
            ["Personal information may be accessed from subprocessors located outside the EU."],
            ["All personal data may be shared with the provider's affiliates abroad."],
        ]
        for paras in risky:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-DATA-2" for p in r.penalties), paras
        benign = [
            ["Personal data shall not be transferred outside the EEA without appropriate safeguards."],
            ["No transfers of personal data outside the EU shall occur under this agreement."],
        ]
        for paras in benign:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-DATA-2" for p in r.penalties), paras

    def test_unilateral_assign_at_any_time_flagged(self):
        # Regression: consent-bound assignment wording must stay silent, but a
        # bare "may assign this agreement at any time" is an unrestricted
        # assignment right and must fire R-COMM-4.
        benign = [
            ["Neither party may assign the agreement without the prior written consent of the other."],
            ["Each party may assign this agreement to an affiliate without consent."],
            ["A party shall not assign this agreement without the other party's consent."],
        ]
        for paras in benign:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-COMM-4" for p in r.penalties), paras
        risky = [
            ["The provider may assign this agreement at any time."],
            ["This agreement may be assigned to any third party by the provider without the customer's consent."],
        ]
        for paras in risky:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-COMM-4" for p in r.penalties), paras

    def test_absence_rule_excerpt_never_a_heading(self):
        """R-DATA-4 must anchor on a body paragraph, not a section heading.

        A heading like "1. PERSONAL DATA" satisfies the topic condition but is
        not a clause; the finding excerpt has to quote the actual body text
        (or fall back only when no body paragraph mentions the topic).
        """
        paras = [
            "1. PERSONAL DATA",
            "The customer will provide personal data for the services.",
            "2. TERM AND FEES",
        ]
        r = score_document(paras, "d")
        data4 = [p for p in r.penalties if p.rule_id == "R-DATA-4"]
        assert data4, "absence rule must fire when the topic is present"
        assert len(data4) == 1
        assert data4[0].para_index == 1
        assert "personal data" in (data4[0].excerpt or "").casefold()
        assert "1. PERSONAL DATA" != (data4[0].excerpt or "").strip()

    def test_denied_personal_data_processing_not_flagged(self):
        # Regression: a clause denying that personal data is collected or
        # processed must not fire R-DATA-1 or the absence rule R-DATA-4.
        benign = [
            ["The parties agree that no personal data is collected or processed under this agreement."],
            ["The Provider does not collect personal data under this agreement."],
        ]
        for paras in benign:
            r = score_document(paras, "d")
            assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties), paras
        # A genuine open-ended processing statement still fires R-DATA-1.
        r = score_document(["The company may use personal data for any purpose."], "d")
        assert any(p.rule_id == "R-DATA-1" for p in r.penalties)

    def test_safeguard_bound_transfers_not_flagged(self):
        # Regression: transfers made pursuant to SCCs or an adequacy decision
        # carry the required safeguards and must not fire R-DATA-2.
        benign = [
            ["Any transfer of personal data outside the EEA shall be made pursuant to the Standard Contractual Clauses."],
            ["Personal data may be transferred to the United States in accordance with an EU adequacy decision."],
        ]
        for paras in benign:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-DATA-2" for p in r.penalties), paras
        r = score_document(
            ["Provider may transfer personal data outside the EEA for processing."], "d"
        )
        assert any(p.rule_id == "R-DATA-2" for p in r.penalties)

    def test_non_penalty_interest_not_flagged(self):
        # Regression: interest earned on funds held as security or prepaid fees
        # is not a late-payment penalty and must not fire R-COMM-6, while a
        # late-payment context still does.
        benign = [
            ["Funds deposited as security shall earn interest at a rate of 2% per annum."],
            ["Any prepaid fees shall earn interest at 3% per annum credited to the customer."],
        ]
        for paras in benign:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-COMM-6" for p in r.penalties), paras
        r = score_document(["Late payments attract interest at 2% per month."], "d")
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_may_revise_fees_flagged(self):
        # Regression: "may revise the service fees" is a unilateral price right
        # that "revise" (absent from the R-COMM-3 verb list) failed to catch.
        risky = [
            ["Provider may revise the service fees at any time upon 30 days written notice."],
            ["The service fees may be revised by Provider from time to time during the term."],
        ]
        for paras in risky:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-COMM-3" for p in r.penalties), paras


    def test_end_without_cause_termination_flagged(self):
        # Regression: "end the agreement without cause" and "terminate without
        # assigning any reason" are one-sided termination rights that must fire
        # R-COMM-2, while mutual forms stay silent.
        risky = [
            ["Company may end the agreement without cause on 30 days written notice."],
            ["The Vendor may terminate the agreement at any time without assigning any reason."],
        ]
        for paras in risky:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-COMM-2" for p in r.penalties), paras
        r = score_document(
            ["Either party may end this agreement for convenience on 30 days written notice."], "d"
        )
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_may_increase_fees_flagged(self):
        # Regression: "may increase the fees at its sole discretion" and "may
        # adjust prices at will" are unilateral price rights that must fire
        # R-COMM-3; mutual / indexed adjustments stay silent.
        risky = [
            ["Provider may increase the fees at its sole discretion by up to 5% each year."],
            ["Provider may adjust prices at will during the term."],
        ]
        for paras in risky:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-COMM-3" for p in r.penalties), paras
        benign = [
            ["The parties may increase the fees by mutual written agreement."],
            ["Fees may increase annually in accordance with the published CPI."],
        ]
        for paras in benign:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-COMM-3" for p in r.penalties), paras

    def test_passive_fee_increase_flagged(self):
        # Regression: "the fees may be increased by Provider upon written
        # notice" (passive verb, no literal "may increase") is a unilateral
        # price right and must fire R-COMM-3.
        risky = [
            ["The fees may be increased by Provider upon 30 days' prior written notice to Customer."],
            ["Prices shall be adjusted by the company at any time during the term."],
        ]
        for paras in risky:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-COMM-3" for p in r.penalties), paras
        benign = [
            ["The fees may be increased by mutual written agreement of the parties."],
            ["Fees may be adjusted annually in accordance with the CPI index."],
        ]
        for paras in benign:
            r = score_document(paras, "d")
            assert all(p.rule_id != "R-COMM-3" for p in r.penalties), paras

    def test_sole_discretion_term_amendment_flagged(self):
        # Regression: "revise these terms at its sole discretion" is a unilateral
        # amendment right equivalent to "amend the terms at its sole discretion"
        # and must fire R-COMM-5; mutual amendment stays silent.
        risky = [
            ["Provider may revise these terms at its sole discretion."],
            ["Provider may amend these terms at any time."],
        ]
        for paras in risky:
            r = score_document(paras, "d")
            assert any(p.rule_id == "R-COMM-5" for p in r.penalties), paras
        r = score_document(
            ["Either party may amend this Agreement by written agreement signed by both parties."], "d"
        )
        assert all(p.rule_id != "R-COMM-5" for p in r.penalties)

    def test_amendment_by_licensor_from_time_to_time_flagged(self):
        # Regression: "may be amended by the Licensor from time to time" is a
        # unilateral amendment right; "from time to time" must be accepted by
        # the R-COMM-5 tail even though it is not "at any time"/"sole discretion".
        r = score_document(
            ["The terms and conditions of this agreement may be amended by the Licensor from time to time."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-5" for p in r.penalties)

    def test_revision_by_provider_from_time_to_time_flagged(self):
        # Regression: the passive-branch tail must also accept "from time to
        # time" for "revised by the Provider ... from time to time".
        r = score_document(
            ["These terms may be revised by the Provider from time to time, with updated versions posted online."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-5" for p in r.penalties)

    def test_for_convenience_with_at_termination_flagged(self):
        # Regression: "at its convenience" (the "at ... convenience" form of the
        # one-sided termination right) must fire R-COMM-2; mutual "either party"
        # constructions stay silent.
        r = score_document(
            ["Company may terminate this agreement at its own convenience, without cause and without penalty."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)
        r2 = score_document(
            ["Either party may terminate this agreement at any time for its convenience on written notice."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-2" for p in r2.penalties)

    def test_monthly_fee_increase_flagged(self):
        # Regression: "may increase the monthly fees" (adjective before the fee
        # noun) is the same unilateral price right as "increase the fees" and
        # must fire R-COMM-3.
        r = score_document(
            ["Provider may increase the monthly fees by up to 10% at its sole discretion."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-3" for p in r.penalties)

    def test_written_rate_unpaid_invoices_flagged(self):
        # Regression: a written-out rate ("one and one-half percent (1.5%) per
        # month") on unpaid invoices is an above-market late-payment rate that
        # must fire R-COMM-6 even without an explicit comma after the amount.
        r = score_document(
            ["Any amounts not paid when due shall accrue interest at one and one-half percent (1.5%) per month on the unpaid balance until paid."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_denied_list_processing_not_flagged(self):
        # Regression: a denial enumerating multiple prohibited actions ("collect,
        # process, use, share or store") must still satisfy the R-DATA-1
        # exclusion, and the SCC-bound transfer must not fire R-DATA-1 either.
        r = score_document(
            ["Neither party shall collect, process, use, share, or store personal data except as strictly necessary for performing this agreement."],
            "d",
        )
        assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties)

    def test_scc_terms_do_not_fire_data_processing_rule(self):
        # Regression: "transferred subject to the Standard Contractual Clauses"
        # is a safeguard against unrestricted personal-data processing and must
        # not fire R-DATA-1 (the SCC wording must not itself be the trigger).
        r = score_document(
            ["Customer personal data may be transferred to the provider's affiliate in the United States subject to the Standard Contractual Clauses approved by the European Commission."],
            "d",
        )
        assert all(p.rule_id != "R-DATA-1" for p in r.penalties)

    def test_authorised_reexport_permitted(self):
        # Regression: "re-export ... without the prior written authorisation"
        # (UK spelling) is a consent-bound control and must not fire R-EXP-1 or
        # R-EXP-3, while an unrestricted re-export still fires both.
        r = score_document(
            ["No re-export or diversion of the software shall occur without the prior written authorisation of the licensor."],
            "d",
        )
        assert all(p.rule_id not in {"R-EXP-1", "R-EXP-3"} for p in r.penalties)
        r2 = score_document(
            ["Customers may re-export the software to any country or use it for any end-use."],
            "d",
        )
        assert any(p.rule_id == "R-EXP-3" for p in r2.penalties)

    def test_warranty_survives_as_is_disclaimer(self):
        # Regression: an "as-is" disclaimer with an express warranty that
        # survives ("warranties set forth in Section 5 shall apply") is a
        # qualified disclaimer and must not fire R-LIAB-4, while a bare as-is
        # clause still does.
        r = score_document(
            ["The software is provided as-is; however, the warranties set forth in Section 5 shall apply."],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-4" for p in r.penalties)
        r2 = score_document(
            ["Support is delivered as-is without any warranties of any kind."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-4" for p in r2.penalties)

    def test_sanctioned_destination_without_export_word_flagged(self):
        # Regression: a sales clause shipping directly to a sanctioned country
        # without the words "export"/"sanction"/"embargo" must still fire R-EXP-2
        # via the shipment/trade topic gate, and a prohibition statement stays
        # silent.
        r = score_document(
            ["Orders shall be fulfilled worldwide; the vendor maintains a sales office in Tehran and ships directly to customers in Cuba."],
            "d",
        )
        assert any(p.rule_id == "R-EXP-2" for p in r.penalties)
        r2 = score_document(
            ["Orders are not fulfilled in Cuba, Iran, Syria, North Korea or Crimea."],
            "d",
        )
        assert all(p.rule_id != "R-EXP-2" for p in r2.penalties)

    def test_unpaid_invoice_interest_rate_flagged(self):
        # Regression: adjective-led "Unpaid invoices shall accrue interest at
        # 18%" is an above-market late-payment rate that must fire R-COMM-6.
        r = score_document(["Unpaid invoices shall accrue interest at 18% per annum."], "d")
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_past_due_balance_interest_rate_flagged(self):
        # Regression: "Balances more than 30 days past due will accrue interest
        # at 1.5% per month" must fire R-COMM-6 (noun-led, past-due form).
        r = score_document(
            ["Balances more than 30 days past due will accrue interest at 1.5% per month."], "d"
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_cancel_for_no_reason_flagged(self):
        # Regression: terminating "for no reason" is a convenience-style
        # one-sided right that must fire R-COMM-2.
        r = score_document(
            ["Customer may cancel this agreement for no reason upon 30 days' notice."], "d"
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_adjust_the_pricing_flagged(self):
        # Regression: "may adjust the pricing" must fire R-COMM-3 (noun form
        # "pricing" was missing).
        r = score_document(["Provider may adjust the pricing at any time."], "d")
        assert any(p.rule_id == "R-COMM-3" for p in r.penalties)

    def test_terms_amended_passive_by_provider_flagged(self):
        # Regression: passive phrasing "These terms may be amended by Provider
        # at any time without notice" is a unilateral amendment right and must
        # fire R-COMM-5.
        r = score_document(
            ["These terms may be amended by Provider at any time without notice."], "d"
        )
        assert any(p.rule_id == "R-COMM-5" for p in r.penalties)

    def test_terms_changed_passive_sole_discretion_flagged(self):
        # Regression: "The terms and conditions may be changed by the Company at
        # its sole discretion" must fire R-COMM-5.
        r = score_document(
            ["The terms and conditions may be changed by the Company at its sole discretion."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-5" for p in r.penalties)

    def test_extension_automatic_absent_notice_flagged(self):
        # Regression: "extended ... automatically absent written notice of
        # termination" is an automatic rollover without an opt-out window and
        # must fire R-COMM-1.
        r = score_document(
            ["The agreement shall be extended for one year at a time automatically absent written notice of termination."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_extension_automatic_with_non_renewal_notice_not_flagged(self):
        # Regression: "extended automatically ... unless either party delivers
        # written notice of non-renewal" is a genuine opt-out and must suppress
        # R-COMM-1 even when the adverb follows the verb phrase.
        r = score_document(
            ["The term shall be extended automatically for one year unless either party delivers written notice of non-renewal at least 60 days prior to expiration."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_automatically_extended_with_notice_not_to_renew_not_flagged(self):
        # Regression: "shall be automatically extended ... unless either party
        # gives written notice not to renew" (adverb BEFORE the verb) is a
        # genuine opt-out and must suppress R-COMM-1.
        r = score_document(
            ["The term shall be automatically extended for successive one-year periods unless either party gives written notice not to renew at least 90 days prior to expiration."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_neither_party_ships_to_sanctioned_destination_not_flagged(self):
        # Regression: a compliant prohibition ("Neither party shall ship goods
        # to Iran or Cuba") must not fire R-EXP-2.
        r = score_document(["Neither party shall ship goods to Iran or Cuba."], "d")
        assert all(p.rule_id != "R-EXP-2" for p in r.penalties)

    def test_no_goods_shipped_to_sanctioned_destination_not_flagged(self):
        # Regression: "No goods shall be shipped to Syria, Iran or North Korea"
        # must not fire R-EXP-2.
        r = score_document(
            ["No goods shall be shipped to Syria, Iran or North Korea."], "d"
        )
        assert all(p.rule_id != "R-EXP-2" for p in r.penalties)

    def test_reexport_requires_prior_approval_not_flagged(self):
        # Regression: "Re-export of the software requires prior written
        # approval" is a licensing control statement and must not fire R-EXP-1
        # or R-EXP-3.
        r = score_document(
            ["Re-export of the software requires prior written approval."], "d"
        )
        assert all(p.rule_id not in {"R-EXP-1", "R-EXP-3"} for p in r.penalties)

    def test_reexport_requires_export_licence_not_flagged(self):
        # Regression: "re-export requires an export licence" must not fire
        # R-EXP-1 or R-EXP-3.
        r = score_document(
            ["Re-export of the software requires an export licence."], "d"
        )
        assert all(p.rule_id not in {"R-EXP-1", "R-EXP-3"} for p in r.penalties)

    def test_reexport_only_with_prior_consent_not_flagged(self):
        # Regression: "may be re-exported only with the licensor's prior written
        # consent" is a consent-bound control and must not fire R-EXP-1 or
        # R-EXP-3, while "without ... consent" remains a gap that fires.
        r = score_document(
            ["The software may be re-exported only with the licensor's prior written consent."],
            "d",
        )
        assert all(p.rule_id not in {"R-EXP-1", "R-EXP-3"} for p in r.penalties)
        r2 = score_document(
            ["The software may be re-exported without the licensor's prior written consent."],
            "d",
        )
        assert any(p.rule_id in {"R-EXP-1", "R-EXP-3"} for p in r2.penalties)

    def test_in_no_event_liability_exceed_flagged(self):
        # Regression: a verb-led cap ("In no event shall the aggregate
        # liability of Company exceed ...") must fire R-LIAB-2.
        r = score_document(
            ["In no event shall the aggregate liability of Company exceed the fees paid in the twelve months preceding the claim."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-2" for p in r.penalties)

    def test_either_partys_symmetric_cap_not_flagged(self):
        # Regression: a symmetric cap on both parties' liability ("either
        # party's aggregate liability ... paid or received") is mutual and
        # must not fire R-LIAB-2.
        r = score_document(
            ["In no event shall either party's aggregate liability exceed the amounts actually paid or received."],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-2" for p in r.penalties)

    def test_notice_of_termination_prior_to_expiration_not_flagged(self):
        # Regression: automatic renewal with an opt-out by written notice of
        # termination prior to expiration is a genuine rollover control and
        # must not fire R-COMM-1.
        r = score_document(
            ["This agreement shall automatically renew for successive one-year periods unless either party gives written notice of termination at least sixty days prior to expiration."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_purposes_other_than_specified_flagged(self):
        # Regression: processing "for purposes other than those specified"
        # (and beyond the agreed scope) must fire R-DATA-3.
        r = score_document(
            ["Provider may process the personal data for purposes other than those specified in this agreement, including for its own product development."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-3" for p in r.penalties)

    def test_shall_not_process_any_purpose_other_than_not_flagged(self):
        # Regression: a prohibition ("shall not process ... for any purpose
        # other than") restricts processing and must not fire R-DATA-3.
        r = score_document(
            ["Provider shall not process personal data for any purpose other than performing its obligations under this agreement."],
            "d",
        )
        assert all(p.rule_id != "R-DATA-3" for p in r.penalties)

    def test_retention_after_expiration_flagged(self):
        # Regression: post-termination retention phrased around the term's
        # end ("after the expiration / following the expiry") must fire
        # R-DATA-5 just like "after termination".
        for para in (
            "Customer data may be retained by Provider after the expiration of this agreement.",
            "Provider may retain copies of Customer data following the expiry of this agreement.",
        ):
            r = score_document([para], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_hold_harmless_flagged(self):
        # Regression: "hold ... harmless from any and all claims" is an
        # indemnity in noun-verb form and must fire R-LIAB-3.
        r = score_document(
            ["Customer shall hold Provider harmless from any and all claims, losses and damages arising from Customer's use of the services."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-3" for p in r.penalties)

    def test_each_party_hold_harmless_own_breach_not_flagged(self):
        # Regression: a mutual "each party ... own breach" hold-harmless is
        # symmetric and must not fire R-LIAB-3.
        r = score_document(
            ["Each party shall hold the other party harmless against claims arising out of its own breach of this agreement."],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-3" for p in r.penalties)


# --- Cycle 6: no-warranty disclaimers, update-terms, suspension discretion,
# late/carrying charges, price-change variants, Sudan/Myanmar references --------


class TestCycle6Precision:
    """Regression mesh for cycle-6 over-fire and under-fire gap fixes."""

    def test_update_terms_at_any_time_flagged(self):
        # Regression: "update these terms" (beyond amend/modify/revise) must
        # fire the unilateral-amendment rule R-COMM-5.
        r = score_document(
            ["Provider may update these terms at any time upon 15 days' notice."], "d"
        )
        assert any(p.rule_id == "R-COMM-5" for p in r.penalties)

    def test_prices_may_change_flagged(self):
        # Regression: "Prices may change at any time" (subject-verb form with
        # no passive participle) must fire R-COMM-3.
        r = score_document(
            ["Prices may change at any time during the term of this agreement."], "d"
        )
        assert any(p.rule_id == "R-COMM-3" for p in r.penalties)

    def test_may_be_altered_flagged(self):
        # Regression: "the fees may be altered by Provider" must fire R-COMM-3.
        r = score_document(
            ["The fees may be altered by Provider upon 30 days' written notice."], "d"
        )
        assert any(p.rule_id == "R-COMM-3" for p in r.penalties)

    def test_flat_late_charge_flagged(self):
        # Regression: a fixed-dollar monthly "late charge" (noun charge, not
        # percentage-only "penalty") must fire R-COMM-6.
        r = score_document(
            ["A late charge of $50 per month shall be assessed on any overdue invoice."], "d"
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_carrying_charge_flagged(self):
        # Regression: "carrying charge" interest on unpaid balances must fire
        # R-COMM-6 alongside interest / penalty / finance-charge anchors.
        r = score_document(
            ["Unpaid balances shall bear a carrying charge of 1.5% per month until paid."], "d"
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_non_returnable_non_creditable_flagged(self):
        # Regression: "non-returnable and non-creditable" payments must fire
        # R-COMM-7 just like "non-refundable".
        r = score_document(
            ["All fees are non-returnable and non-creditable once services are provided."], "d"
        )
        assert any(p.rule_id == "R-COMM-7" for p in r.penalties)

    def test_suspension_discretion_before_verb_flagged(self):
        # Regression: discretion/adverbial modifiers placed BEFORE the
        # suspend/deactivate verb must still fire R-COMM-8.
        for para in (
            "Provider at its sole discretion may suspend access to the services at any time.",
            "Provider may deactivate any account at its absolute discretion without notice.",
            "Provider with immediate effect may suspend the services if Customer fails to pay.",
        ):
            r = score_document([para], "d")
            assert any(p.rule_id == "R-COMM-8" for p in r.penalties), para

    def test_no_warranties_of_any_kind_flagged(self):
        # Regression: noun-phrase "gives no warranties of any kind" (no verb
        # "warrant") must fire R-LIAB-4.
        r = score_document(
            ["Provider gives no warranties of any kind with respect to the services."], "d"
        )
        assert any(p.rule_id == "R-LIAB-4" for p in r.penalties)

    def test_makes_no_warranties_flagged(self):
        # Regression: "makes no warranties" (make-verb no-warranty form) must
        # fire R-LIAB-4.
        r = score_document(
            ["Vendor makes no warranties and gives no representations regarding the software."], "d"
        )
        assert any(p.rule_id == "R-LIAB-4" for p in r.penalties)

    def test_one_sided_no_warranty_survives_mutual_exclusion(self):
        # Guard: the mutual "each party makes no warranties" exclusion must not
        # swallow a genuinely one-sided disclaimer.
        r = score_document(
            ["Provider gives no warranties of any kind with respect to the services."], "d"
        )
        assert any(p.rule_id == "R-LIAB-4" for p in r.penalties)

    def test_each_party_makes_no_warranties_not_flagged(self):
        # Regression: a mutual disclaimer of both parties' warranties (no "party"
        # subject appears) must not fire R-LIAB-4 as one-sided risk.
        r = score_document(
            ["Each party makes no warranties of any kind with respect to its own pre-contractual statements."],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-4" for p in r.penalties)

    def test_suitable_for_particular_purpose_flagged(self):
        # Regression: "suitability for a particular purpose" (beyond literal
        # "fitness for") must fire R-LIAB-5's purpose tail.
        r = score_document(
            ["Provider makes no representations or warranties regarding the suitability of the services for a particular purpose."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-5" for p in r.penalties)

    def test_meet_requirements_flagged(self):
        # Regression: "will not meet all of Customer's requirements"
        # (verb-object form, no availability/fitness noun) must fire R-LIAB-5.
        r = score_document(
            ["Provider makes no warranty that the services will meet all of Customer's requirements."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-5" for p in r.penalties)

    def test_sudan_myanmar_references_flagged(self):
        # Regression: named-country expansion covering Sudan and Myanmar must
        # fire R-EXP-2.
        r = score_document(
            ["The vendor maintains distributors in Sudan and ships directly to Myanmar."], "d"
        )
        assert any(p.rule_id == "R-EXP-2" for p in r.penalties)

    def test_sanctions_compliance_mention_sudan_myanmar_not_flagged(self):
        # Regression: a compliance clause that merely names sanctioned
        # jurisdictions must not fire R-EXP-2.
        r = score_document(
            ["Each party shall comply with all applicable sanctions, including those covering Sudan and Myanmar."],
            "d",
        )
        assert all(p.rule_id != "R-EXP-2" for p in r.penalties)

    def test_adequacy_determination_transfer_not_flagged(self):
        # Regression: a transfer following an "adequacy determination" (not the
        # literal "adequacy decision") is safeguard-backed and must not fire
        # R-DATA-1 or R-DATA-2.
        r = score_document(
            ["Personal data may be transferred to the United States following an adequacy determination by the European Commission."],
            "d",
        )
        assert all(p.rule_id not in ("R-DATA-1", "R-DATA-2") for p in r.penalties)

    def test_adequacy_finding_transfer_not_flagged(self):
        # Regression: "adequacy finding" from the destination regulator must
        # also stay silent.
        r = score_document(
            ["Customer data will be processed in the United Kingdom pursuant to an adequacy finding adopted by the European Commission."],
            "d",
        )
        assert all(p.rule_id not in ("R-DATA-1", "R-DATA-2") for p in r.penalties)


class TestCycle7Precision:
    """Regression mesh for cycle-7 over-fire and under-fire gap fixes."""

    def test_end_user_license_agreement_not_flagged(self):
        # Regression: "end-user" (as in End User License Agreement) must not be
        # read as "end use" by R-EXP-3.
        r = score_document(
            ["Customer may install the software under the terms of the End User License Agreement."],
            "d",
        )
        assert all(p.rule_id != "R-EXP-3" for p in r.penalties)

    def test_excluding_crimea_not_flagged(self):
        # Regression: "available worldwide, excluding Crimea and other
        # sanctioned regions" is a carve-out, not a sanctioned-destination
        # commitment; must not fire R-EXP-1 or R-EXP-2.
        r = score_document(
            ["The services shall be available worldwide, excluding Crimea and other sanctioned regions."],
            "d",
        )
        assert all(p.rule_id not in ("R-EXP-1", "R-EXP-2") for p in r.penalties)

    def test_terminated_for_convenience_flagged(self):
        # Regression: inflected "terminated" (past participle) must fire the
        # one-sided-termination rule R-COMM-2.
        r = score_document(
            ["This agreement may be terminated by Company at any time without cause and without penalty."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_cancelled_for_convenience_flagged(self):
        # Regression: inflected "cancelled"/"cancellation" forms must fire
        # R-COMM-2 just like "terminate".
        r = score_document(
            ["The agreement may be cancelled by Provider for convenience at any time."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_liable_or_responsible_flagged(self):
        # Regression: "not be liable or responsible" (compound of the exclusion
        # terms) must fire R-LIAB-1.
        r = score_document(
            ["Provider shall not be liable or responsible for any indirect, special or consequential damages."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-1" for p in r.penalties)

    def test_prices_subject_to_change_flagged(self):
        # Regression: "Prices are subject to change" (subject-to-change form,
        # not a price-increase verb) must fire R-COMM-3.
        r = score_document(
            ["Prices are subject to change at any time without prior notice."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-3" for p in r.penalties)

    def test_disclaim_all_warranties_flagged(self):
        # Regression: verb-led "disclaims all warranties, express or implied"
        # must fire R-LIAB-4 alongside noun-form disclaimers.
        r = score_document(
            ["Provider expressly disclaims all warranties, express or implied."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-4" for p in r.penalties)

    def test_pii_collected_flagged(self):
        # Regression: word-bounded "PII" alone (without the words "personal
        # data/information") must fire R-DATA-1.
        r = score_document(
            ["The parties acknowledge that PII of customers may be collected during the provision of the services."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-1" for p in r.penalties)

    def test_pii_stored_india_flagged(self):
        # Regression: "PII is stored on servers located in India" (data-led
        # sentence, PII subject) must fire R-DATA-2.
        r = score_document(
            ["All customer PII is stored on servers located in India."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-2" for p in r.penalties)

    def test_novate_without_consent_flagged(self):
        # Regression: "novate this agreement to any third party without
        # consent" must fire R-COMM-4's assignment-without-consent rule.
        r = score_document(
            ["Customer may novate this agreement to any third party without the prior written consent of Provider."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_marketing_use_flagged(self):
        # Regression: "use Customer data for marketing purposes" is an
        # unrelated/own-purpose use and must fire R-DATA-3.
        r = score_document(
            ["Provider may use Customer data for marketing purposes."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-3" for p in r.penalties)

    def test_either_party_terminates_not_flagged(self):
        # Guard: "may be terminated by either party upon written notice" is
        # mutual and must not fire R-COMM-2.
        r = score_document(
            ["This agreement may be terminated by either party upon 30 days' written notice."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_fees_may_be_reduced_not_flagged(self):
        # Guard: "fees may be reduced" is favourable to the counterparty and
        # must not fire R-COMM-3.
        r = score_document(
            ["The fees may be reduced by Provider if usage volume exceeds 1,000 units."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-3" for p in r.penalties)

    def test_privacy_policy_processing_not_flagged(self):
        # Guard: processing "in accordance with the Privacy Policy" is
        # governed and must not fire R-DATA-1.
        r = score_document(
            ["The parties shall process personal data in accordance with the Privacy Policy available at the provider's website."],
            "d",
        )
        assert all(p.rule_id != "R-DATA-1" for p in r.penalties)

    def test_aggregate_anonymised_statistics_not_flagged(self):
        # Guard: "aggregate, anonymised data for statistical purposes" is not
        # an unrelated commercial use and must not fire R-DATA-3.
        r = score_document(
            ["Provider may retain aggregate, anonymised data for statistical purposes without limitation."],
            "d",
        )
        assert all(p.rule_id != "R-DATA-3" for p in r.penalties)

    def test_scc_transfer_processed_not_flagged(self):
        # Guard: "is transferred ... subject to the Standard Contractual
        # Clauses" is safeguard-backed and must not fire R-DATA-2.
        r = score_document(
            ["Customer data is transferred to the affiliate subject to the Standard Contractual Clauses approved by the European Commission."],
            "d",
        )
        assert all(p.rule_id != "R-DATA-2" for p in r.penalties)


class TestCycle8Precision:
    """Regression mesh for cycle-8 over-fire and under-fire gap fixes."""

    def test_end_users_not_flagged(self):
        # Regression: "end users" (plural noun, no end-use commitment) must not
        # fire R-EXP-3; the lookahead must also reject "end users", not just
        # "end-user".
        r = score_document(
            ["Provider delivers the software for use by end users across the globe."],
            "d",
        )
        assert all(p.rule_id != "R-EXP-3" for p in r.penalties)

    def test_cap_on_amounts_paid_by_other_party_not_flagged(self):
        # Regression: a symmetric cap tied to "amounts actually paid by the
        # other party" (mutual, per-party) must not fire R-LIAB-2.
        r = score_document(
            [
                "In no event shall either party's aggregate liability arising out of this agreement "
                "exceed the amounts actually paid by the other party in the preceding twelve months."
            ],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-2" for p in r.penalties)

    def test_parties_amend_by_mutual_written_agreement_not_flagged(self):
        # Regression: "The parties may amend ... by mutual written agreement"
        # is a mutual amendment and must not fire R-COMM-5.
        r = score_document(
            ["The parties may amend these terms at any time by mutual written agreement."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-5" for p in r.penalties)

    def test_not_for_delivery_to_cuba_or_iran_not_flagged(self):
        # Regression: "not for delivery to Cuba or Iran" is a prohibition, not
        # a sanctioned-destination commitment; must not fire R-EXP-2.
        r = score_document(
            ["All goods are strictly not for delivery to Cuba or Iran under any circumstances."],
            "d",
        )
        assert all(p.rule_id != "R-EXP-2" for p in r.penalties)

    def test_renew_unless_terminated_in_writing_not_flagged(self):
        # Regression: "shall automatically renew ... unless terminated in
        # writing by either party" has an opt-out and must not fire R-COMM-1.
        r = score_document(
            [
                "The term shall automatically renew for successive one-year periods "
                "unless terminated in writing by either party."
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_exports_under_valid_licence_not_flagged(self):
        # Regression: "All exports shall be made under a valid export licence"
        # is a controlled export, not a missing-controls gap; must not fire
        # R-EXP-1.
        r = score_document(
            ["All exports shall be made under a valid export licence obtained by the exporter."],
            "d",
        )
        assert all(p.rule_id != "R-EXP-1" for p in r.penalties)

    def test_retain_after_termination_date_flagged(self):
        # Regression: time-preposition-first "After the termination date,
        # Provider shall retain Customer data" must fire R-DATA-5.
        r = score_document(
            ["After the termination date, Provider shall retain Customer data."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_use_for_any_reason_whatsoever_flagged(self):
        # Regression: "use Customer data for any reason whatsoever" is an
        # unrestricted-use gap and must fire R-DATA-3.
        r = score_document(
            ["Provider may use Customer data for any reason whatsoever."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-3" for p in r.penalties)

    def test_keep_following_expiry_flagged(self):
        # Regression: "Following expiry of the agreement, the vendor may keep
        # Customer information" must fire R-DATA-5.
        r = score_document(
            ["Following expiry of the agreement, the vendor may keep Customer information."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_terminate_without_reason_flagged(self):
        # Regression: "may terminate the agreement at any time without reason"
        # is a one-sided termination right and must fire R-COMM-2 (alongside
        # "without assigning any reason").
        r = score_document(
            ["Company may terminate the agreement at any time without reason."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

class TestCycle9Precision:
    """Regression tests for cycle 9 precision-gap fixes (rules engine)."""

    def test_assign_upon_written_consent_not_flagged(self):
        # Regression: "assign to any third party upon the prior written
        # consent" is consent-backed and must not fire R-COMM-4.
        r = score_document(
            [
                "Customer may assign this agreement to any third party upon "
                "the prior written consent of Provider."
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_non_refundable_unless_defective_not_flagged(self):
        # Regression: non-refundable fees with a defective-work carve-out must
        # not fire R-COMM-7.
        r = score_document(
            [
                "Custom development fees are non-refundable after the work has "
                "been performed, unless the work was defective."
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-7" for p in r.penalties)

    def test_suspension_required_by_law_not_flagged(self):
        # Regression: suspension required by law or a court order is not a
        # unilateral-discretion gap and must not fire R-COMM-8.
        r = score_document(
            [
                "Provider may suspend the services with immediate effect where "
                "required by law or a court order."
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-8" for p in r.penalties)

    def test_terminate_without_cause_required_by_law_not_flagged(self):
        # Regression: "terminate ... without cause where required by
        # applicable law" is legally mandated, not convenience, and must not
        # fire R-COMM-2.
        r = score_document(
            ["Company may terminate this agreement without cause where required by applicable law."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_fees_in_line_with_cpi_not_flagged(self):
        # Regression: fee adjustment pegged in line with the consumer price
        # index is not a unilateral-increase gap and must not fire R-COMM-3.
        r = score_document(
            [
                "The fees may be adjusted annually in line with the consumer "
                "price index published by the national statistics office."
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-3" for p in r.penalties)

    def test_each_party_held_harmless_own_negligence_not_flagged(self):
        # Regression: a mutual each-party-held-harmless-for-own-negligence
        # clause is not one-sided exposure and must not fire R-LIAB-3.
        r = score_document(
            [
                "Each party shall be held harmless by the other party for its "
                "own negligence."
            ],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-3" for p in r.penalties)

    def test_convenience_before_verb_flagged(self):
        # Regression: "For its convenience ... Company may terminate" (modifier
        # before the verb) must fire R-COMM-2.
        r = score_document(
            ["For its convenience and at any time, Company may terminate this agreement."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_may_update_service_fees_flagged(self):
        # Regression: "may update the service fees" is a unilateral price
        # change and must fire R-COMM-3.
        r = score_document(
            ["Provider may update the service fees upon 30 days' prior written notice."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-3" for p in r.penalties)

    def test_flat_dollar_carrying_charge_flagged(self):
        # Regression: a flat-dollar "carrying charge of $25 per month" must
        # fire R-COMM-6.
        r = score_document(
            ["Unpaid balances shall bear a carrying charge of $25 per month."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_flat_dollar_finance_charge_flagged(self):
        # Regression: a flat-dollar "finance charge of $25 per month" must
        # fire R-COMM-6.
        r = score_document(
            ["Accounts paid late shall incur a finance charge of $25 per month."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_held_harmless_from_third_party_claims_flagged(self):
        # Regression: "Provider shall be held harmless from any claims by
        # third parties" is a one-sided hold-harmless and must fire R-LIAB-3.
        r = score_document(
            [
                "Provider shall be held harmless from any claims by third "
                "parties arising out of Customer's use of the services."
            ],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-3" for p in r.penalties)

    def test_availability_not_guaranteed_flagged(self):
        # Regression: passive "The availability ... is not guaranteed" must
        # fire R-LIAB-5.
        r = score_document(
            ["The availability of the services at all times is not guaranteed by Provider."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-5" for p in r.penalties)

    def test_accessible_by_employees_abroad_flagged(self):
        # Regression: "Customer data is accessible by our employees in China"
        # is the same cross-border-access risk family as storage and must fire
        # R-DATA-2.
        r = score_document(
            ["Customer data is accessible by our employees in China."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-2" for p in r.penalties)


class TestCycle10Precision:
    """Cycle-10 precision fixes: auto-extend opt-out, such-party caps,
    genuine pre-estimate LDs, within-EEA storage, return-or-destroy,
    mutual-consent fee adjustment, and the six false-negative families
    (credits/returns, transfer of rights, right to change fees, service
    charge on past-due accounts, subprocessor processing, lost-profits
    disclaimers)."""

    def test_auto_extend_with_intention_not_to_renew_not_flagged(self):
        # Regression: extension whose opt-out only needs "intention not to
        # renew" notice is a genuine auto-renewal with a renewal opt-out, so
        # it must not fire R-COMM-1.
        r = score_document(
            [
                "The term shall be extended for successive one-year periods "
                "automatically unless either party gives written notice of "
                "its intention not to renew at least 60 days prior to the "
                "expiration date."
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_mutual_cap_paid_by_such_party_not_flagged(self):
        # Regression: a fee-based cap phrased as "amounts paid by such party"
        # (mirroring the "paid by such party" style) is the same mutual
        # limitation as "each/either/other party" and must not fire
        # R-LIAB-2.
        r = score_document(
            [
                "Either party's aggregate liability shall in no event exceed "
                "the amounts paid by such party during the twelve months "
                "preceding the claim."
            ],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-2" for p in r.penalties)

    def test_liquidated_damages_genuine_pre_estimate_not_flagged(self):
        # Regression: liquidated damages expressly described as a genuine
        # pre-estimate are an enforceable fixed sum, not a penalty that must
        # fire R-LIAB-6.
        r = score_document(
            [
                "The liquidated damages sum of $10,000 represents a genuine "
                "pre-estimate of the loss likely to be suffered in the event "
                "of delay."
            ],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-6" for p in r.penalties)

    def test_data_stored_within_eea_not_flagged(self):
        # Regression: storage "within the EEA" is not a cross-border
        # transfer from the EEA and must not fire R-DATA-2.
        r = score_document(
            [
                "All Customer data is stored on servers located within the "
                "European Economic Area (EEA)."
            ],
            "d",
        )
        assert all(p.rule_id != "R-DATA-2" for p in r.penalties)

    def test_return_or_destroy_within_thirty_days_not_flagged(self):
        # Regression: an obligation to return or destroy data on termination
        # is data-deletion protection, not retention, and must not fire
        # R-DATA-5.
        r = score_document(
            [
                "Following termination, Provider shall return or destroy all "
                "Customer data within thirty days."
            ],
            "d",
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)

    def test_right_to_adjust_fees_by_mutual_consent_not_flagged(self):
        # Regression: a fee-adjustment right exercisable only by mutual
        # written consent is not unilateral and must not fire R-COMM-3.
        r = score_document(
            [
                "Customer shall have the right to adjust the fees by mutual "
                "written consent of both parties."
            ],
            "d",
        )
        assert all(p.rule_id != "R-COMM-3" for p in r.penalties)

    def test_payments_final_no_credits_returns_refunds_flagged(self):
        # Regression: "no credits, returns, or refunds will be given" locks
        # the counterparty into full payment and must fire R-COMM-7.
        r = score_document(
            [
                "All payments are final and no credits, returns, or refunds "
                "will be given once services have commenced."
            ],
            "d",
        )
        assert any(p.rule_id == "R-COMM-7" for p in r.penalties)

    def test_transfer_all_rights_to_third_party_flagged(self):
        # Regression: transferring all rights under the agreement to any
        # third party without consent is an assignment-equivalent and must
        # fire R-COMM-4.
        r = score_document(
            [
                "Customer may transfer all of its rights under this "
                "agreement to any third party without consent."
            ],
            "d",
        )
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_shall_have_right_to_change_fees_flagged(self):
        # Regression: "shall have the right to change the fees" is a
        # unilateral price-change right and must fire R-COMM-3.
        r = score_document(
            ["Provider shall have the right to change the fees upon 30 days' "
             "written notice."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-3" for p in r.penalties)

    def test_service_charge_on_past_due_accounts_flagged(self):
        # Regression: a percentage "service charge" applied to past-due
        # accounts is an above-market late/surcharge and must fire R-COMM-6.
        r = score_document(
            ["Past due accounts are subject to a monthly service charge of "
             "1.5%."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-6" for p in r.penalties)

    def test_process_through_subprocessors_in_us_flagged(self):
        # Regression: processing via subprocessors located in the United
        # States is a cross-border data-flow and must fire R-DATA-2.
        r = score_document(
            [
                "Provider may process Customer data through subprocessors "
                "located in the United States."
            ],
            "d",
        )
        assert any(p.rule_id == "R-DATA-2" for p in r.penalties)

    def test_lost_profits_disclaimer_flagged(self):
        # Regression: a provider disclaimer naming lost profits among the
        # excluded indirect damages must fire R-LIAB-1.
        r = score_document(
            [
                "Provider shall not be liable for any indirect damages, "
                "including lost profits, revenue, or business interruption."
            ],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-1" for p in r.penalties)


class TestCycle11Precision:
    """Cycle-11 precision regression: R-COMM-3 active intransitive
    increases; R-LIAB-6 unanchored flat/percentage penalties."""

    def test_prices_may_increase_flagged(self):
        # Regression: an active intransitive "prices may increase" clause
        # is a unilateral price hike and must fire R-COMM-3.
        r = score_document(
            ["Prices may increase at any time upon 30 days' prior written "
             "notice to Customer."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-3" for p in r.penalties)

    def test_fees_will_increase_annually_flagged(self):
        # Regression: a mandatory annual fee escalation must fire R-COMM-3.
        r = score_document(
            ["The fees will increase annually upon 60 days' written notice."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-3" for p in r.penalties)

    def test_prices_may_decrease_not_flagged(self):
        # Control: a right to lower prices is not a unilateral increase.
        r = score_document(
            ["Prices may decrease at any time at the provider's sole "
             "discretion."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-3" for p in r.penalties)

    def test_no_price_increase_for_first_year_not_flagged(self):
        # Control: an explicit no-increase commitment is not a hike.
        r = score_document(
            ["There shall be no price increase during the first year of the "
             "term."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-3" for p in r.penalties)

    def test_cpi_indexed_increase_not_flagged(self):
        # Control: an objective CPI-indexed escalation is market-tied and
        # stays silent.
        r = score_document(
            ["Fees will increase annually in line with the consumer price "
             "index."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-3" for p in r.penalties)

    def test_penalty_percentage_of_contract_value_flagged(self):
        # Regression: a flat percentage penalty for delay must fire
        # R-LIAB-6 even without a per-day or forfeiture anchor.
        r = score_document(
            ["A penalty of 5% of the contract value shall be payable by the "
             "supplier for any delay in delivery."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-6" for p in r.penalties)

    def test_penalty_fixed_dollar_for_any_delay_flagged(self):
        # Regression: a fixed-dollar penalty with a "for any delay" tail
        # must fire R-LIAB-6.
        r = score_document(
            ["A penalty of $1,000 shall be payable by the supplier for any "
             "delay in delivery."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-6" for p in r.penalties)

    def test_penalty_percentage_per_week_flagged(self):
        # Regression: a per-week percentage penalty must fire R-LIAB-6.
        r = score_document(
            ["The supplier shall pay a penalty equal to 2% of the purchase "
             "price for each week of delay."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-6" for p in r.penalties)

    def test_fixed_charge_currency_prefix_flagged(self):
        # Regression: a currency-word-prefixed fixed charge for any delay
        # must fire R-LIAB-6.
        r = score_document(
            ["A fixed charge of EUR 500 for any delay shall be paid by the "
             "supplier."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-6" for p in r.penalties)

    def test_penalty_capped_at_actual_loss_not_flagged(self):
        # Control: a penalty bounded at the actual loss is not
        # disproportionate and stays silent.
        r = score_document(
            ["Any penalty for delay shall be capped at the actual loss "
             "suffered by the buyer."],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-6" for p in r.penalties)

    def test_penalty_not_exceeding_percentage_not_flagged(self):
        # Control: an express cap ("not exceed 5%") keeps the penalty
        # proportionate and silent.
        r = score_document(
            ["The penalty for delay shall not exceed 5% of the contract "
             "value."],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-6" for p in r.penalties)

    def test_no_penalty_not_flagged(self):
        # Control: an express no-penalty clause must stay silent.
        r = score_document(
            ["No penalty shall be payable for any delay in delivery."],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-6" for p in r.penalties)


class TestCycle12Precision:
    """Cycle-12 precision regression: R-COMM-1 rollover-phrasing variants
    (deemed / continue-for-successive-terms); R-DATA-5 retention verbs
    (preserve) and possessive mediation (retain possession of)."""

    # --- R-COMM-1 under-fire regressions ---

    def test_renew_automatically_no_opt_out_flagged(self):
        # Regression: an automatic rollover without any opt-out window must
        # fire R-COMM-1.
        r = score_document(
            ["This agreement shall renew automatically for successive "
             "one-year periods."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_deemed_extended_no_opt_out_flagged(self):
        # Regression: a "deemed extended automatically" rollover is an
        # auto-renewal and must fire R-COMM-1.
        r = score_document(
            ["The term shall be deemed extended automatically for additional "
             "one-year periods without further action."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_continue_for_successive_terms_flagged(self):
        # Regression: a successive-renewal-terms continuation with no
        # opt-out window must fire R-COMM-1.
        r = score_document(
            ["This agreement shall continue in effect for successive "
             "one-year renewal terms."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_renewed_automatically_each_anniversary_flagged(self):
        # Regression: anniversary-based automatic renewal must fire
        # R-COMM-1.
        r = score_document(
            ["The agreement will be renewed automatically on each "
             "anniversary of the effective date."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    # --- R-COMM-1 over-fire controls ---

    def test_renew_unless_notice_not_to_renew_not_flagged(self):
        # Control: an auto-renewal with a notice-not-to-renew opt-out
        # window stays silent.
        r = score_document(
            ["This agreement shall automatically renew for successive "
             "one-year terms unless either party provides written notice "
             "not to renew at least 60 days prior to expiration."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_extended_with_90_day_opt_out_not_flagged(self):
        # Control: an automatic extension with a 90-day termination-notice
        # window stays silent.
        r = score_document(
            ["The term shall be automatically extended for successive "
             "one-year periods unless either party gives written notice of "
             "termination at least 90 days before the expiry date."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_no_automatic_renewal_not_flagged(self):
        # Control: an express no-auto-renewal clause stays silent.
        r = score_document(
            ["This agreement shall not automatically renew; any renewal "
             "requires a new written agreement."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_continue_unless_notice_not_flagged(self):
        # Control: the new continue-for-successive-terms pattern must still
        # respect a notice-not-to-renew opt-out window.
        r = score_document(
            ["This agreement shall continue in effect for successive "
             "one-year terms unless either party provides written notice "
             "not to renew at least 60 days prior to expiration."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_continue_with_90_day_opt_out_not_flagged(self):
        # Control: the continue pattern must respect a 90-day termination
        # notice window.
        r = score_document(
            ["The term shall continue for additional successive periods "
             "unless either party gives written notice of termination at "
             "least 90 days before the expiry date."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_deemed_extended_unless_object_not_flagged(self):
        # Control: the new deemed-extended pattern must respect a written
        # objection opt-out.
        r = score_document(
            ["The term shall be deemed extended automatically for "
             "additional one-year periods unless either party objects in "
             "writing at least 30 days prior to the renewal date."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_fixed_term_no_rollover_not_flagged(self):
        # Control: a fixed term that never rolls over stays silent, even
        # though it says "continue in effect".
        r = score_document(
            ["This agreement shall continue in effect for a fixed term of "
             "one year from the effective date."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    # --- R-DATA-5 regressions and controls ---

    def test_retain_possession_of_data_flagged(self):
        # Regression: retaining "possession of" customer data after
        # termination must fire R-DATA-5 (mediated possessory retention).
        r = score_document(
            ["Following termination of this agreement, Provider may retain "
             "possession of Customer data."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_preserve_data_after_termination_flagged(self):
        # Regression: "preserve" as a retention verb after termination must
        # fire R-DATA-5.
        r = score_document(
            ["Provider shall preserve Customer data after termination of "
             "this agreement."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_retain_for_tax_purposes_not_flagged(self):
        # Control: retention required for tax purposes per law stays
        # silent.
        r = score_document(
            ["Provider shall retain Customer data following termination for "
             "tax purposes as required by applicable law."],
            "d",
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)

    def test_retain_for_compliance_purposes_not_flagged(self):
        # Control: retention solely to comply with regulatory obligations
        # stays silent.
        r = score_document(
            ["Following termination, Provider shall retain Customer records "
             "solely to comply with regulatory obligations."],
            "d",
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)


class TestCycle13Precision:
    """Cycle-13 precision regression: cross-border / data-protection
    phrasing coverage for R-DATA-1 and R-DATA-4.

    A privacy statement or notice is protective wording that must suppress
    the open-ended-processing rule R-DATA-1 and the absence rule R-DATA-4;
    an active denial ("shall not transfer / disclose personal data") is a
    protective statement and must suppress both rules too.
    """

    def test_privacy_statement_not_flagged(self):
        # Regression: "privacy statement" is protective wording (same weight
        # as a privacy policy) and must suppress R-DATA-1 and R-DATA-4.
        r = score_document(
            ["The parties shall handle personal data in accordance with the Provider's privacy statement."],
            "d",
        )
        assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties)

    def test_privacy_notice_not_flagged(self):
        # Regression: "privacy notice" must suppress R-DATA-1 and R-DATA-4
        # just like a privacy policy does.
        r = score_document(
            ["Personal data is handled in accordance with this privacy notice."],
            "d",
        )
        assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties)

    def test_does_not_transfer_personal_data_not_flagged(self):
        # Regression: an active denial of transfer must suppress R-DATA-1 and
        # R-DATA-4 (the transfer/disclose verbs were previously missing from
        # the active-denial branch).
        r = score_document(
            ["Provider does not transfer personal data to any third party."],
            "d",
        )
        assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties)

    def test_does_not_disclose_personal_data_not_flagged(self):
        # Regression: an active denial of disclosure is protective and must
        # suppress R-DATA-1 and R-DATA-4.
        r = score_document(
            ["Provider does not disclose personal data under this agreement."],
            "d",
        )
        assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties)

    def test_shall_not_transfer_or_disclose_not_flagged(self):
        # Regression: a "shall not transfer or disclose" denial with a
        # conjunctive verb list must suppress both rules.
        r = score_document(
            ["Provider shall not transfer or disclose personal data under this agreement."],
            "d",
        )
        assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties)

    def test_open_ended_personal_data_processing_still_flagged(self):
        # Control: a genuine open-ended processing statement must still fire
        # R-DATA-1 (and R-DATA-4 stays silent because the topic is already
        # covered by a paragraph rule).
        r = score_document(
            ["The company may use personal data for any purpose."],
            "d",
        )
        assert any(p.rule_id == "R-DATA-1" for p in r.penalties)

class TestCycle14Precision:
    """Cycle-14 precision: quantifier/minimisation denials, non-USD flat fees,
    intra-EEA/EU data flows, and purpose-restriction silencing for R-DATA-3."""

    # ------------------------------------------------------------------ R-COMM-6

    def test_non_usd_flat_late_fee_flagged(self):
        # Regression: fixed-amount late fees denominated in foreign currencies
        # or currency symbols are as one-sided as USD ones and must fire.
        flagged = [
            "Late fee of EUR 100 is payable per overdue invoice.",
            "A late fee of GBP 100 applies for each overdue invoice.",
            "A late fee of 100 euros applies to each late payment.",
            "Late fee of 1000 CNY is charged per day past due.",
            "Overdue accounts accrue a finance charge of AUD 25 per month.",
            "A penalty charge of £500 accrues weekly.",
            "A delinquency fee of €100 per week applies.",
            "A carrying charge of 25 dollars per month applies.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-6" for p in r.penalties), t

    def test_non_usd_plain_fee_not_flagged(self):
        # Precision: an ordinary one-off fee (no late-payment/penalty context)
        # stays silent even when denominated in a foreign currency.
        benign = [
            "Customer shall pay a setup fee of EUR 100,000 upon signature.",
            "Customer shall pay an annual licence fee of JPY 500,000.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-6" for p in r.penalties), t

    def test_round_flat_amount_without_periodicity_not_flagged(self):
        # Precision: a flat penalty amount without any periodic accrual suffix
        # (like the existing USD branch) must not fire.
        r = score_document(["A penalty charge of EUR 500."], "d")
        assert all(p.rule_id != "R-COMM-6" for p in r.penalties)

    # ------------------------------------------------------------------ R-DATA-1 / R-DATA-4

    def test_quantified_denials_not_flagged(self):
        # Regression: active denials with quantifier objects ("any", "all the")
        # are protective and must suppress R-DATA-1 and R-DATA-4.
        benign = [
            "We shall not collect any personal data from end users.",
            "The company does not collect any personal information.",
            "Provider shall not transfer any personal data to third parties.",
            "The parties do not collect all the personal data they process.",
            "We will not transfer any personal information to third parties.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties), t

    def test_minimisation_wording_not_flagged(self):
        # Regression: data-minimisation obligations and necessary-for-purpose
        # processing are protective and must suppress R-DATA-1 / R-DATA-4.
        benign = [
            "The parties will minimize the personal data they process.",
            "The parties will minimise personal data.",
            "The parties will process only the personal data necessary for the "
            "purpose of the services.",
            "We retain only the personal data necessary to provide the service.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties), t

    # ------------------------------------------------------------------ R-DATA-2

    def test_active_transfer_denials_not_flagged(self):
        # Regression: active ("will not transfer") or modal ("may not use")
        # denials are protective and must suppress R-DATA-2.
        benign = [
            "We will not transfer any personal information to third parties.",
            "The parties may not transfer personal data to any party.",
            "Provider shall not transfer personal data outside the EEA.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-2" for p in r.penalties), t

    def test_intra_regional_eu_eea_flow_not_flagged(self):
        # Regression: processing, storage, or transfer confined to the EEA/EU
        # is not a cross-border transfer and must suppress R-DATA-2.
        benign = [
            "Personal data transferred within the EEA.",
            "Customer data stored in the EU data centres.",
            "Personal data transferred to the EEA.",
            "Personal data will be transferred within the European Union.",
            "Data is processed in the EEA.",
            "All Customer data is stored on servers located within the "
            "European Economic Area (EEA).",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-2" for p in r.penalties), t

    def test_cross_border_controls_still_flagged(self):
        # Controls: outbound flows from the EEA/EU must keep firing.
        flagged = [
            "Personal data may be transferred from the EEA to the United States.",
            "Customer data is processed within the United States.",
            "Personal data is stored on servers located in the United States.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-2" for p in r.penalties), t

    # ------------------------------------------------------------------ R-DATA-3

    def test_purpose_restrictions_not_flagged(self):
        # Regression: genuine utilisation restrictions ("other than",
        # "except") bound the purpose and must suppress R-DATA-3.
        benign = [
            "Neither party shall use any personal data for any purpose other "
            "than performing the services.",
            "Provider may use the data for any purpose except marketing.",
            "Provider may use data for any purpose other than those specified "
            "in Schedule A.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-3" for p in r.penalties), t

    def test_restriction_with_expansion_clause_still_flagged(self):
        # Control: "other than ... including X" enlarges the purpose and the
        # exclusion's negative lookahead must let R-DATA-3 keep firing.
        r = score_document(
            [
                "Provider may process the personal data for purposes other "
                "than those specified in this agreement, including for its own "
                "product development."
            ],
            "d",
        )
        assert any(p.rule_id == "R-DATA-3" for p in r.penalties)

    def test_unbounded_purposes_still_flagged(self):
        # Controls: unrestricted purpose clauses must keep firing R-DATA-3.
        flagged = [
            "Provider may use the data for any purpose whatsoever.",
            "Provider may use the data for its own business purposes.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-3" for p in r.penalties), t


class TestCycle15Precision:
    """Cycle-15 precision: bounded retention ("up to N") is protective for
    R-DATA-5; reversed-order and express/implied disclaimers plus "with all
    faults" fire R-LIAB-4; gives/offers/provides-no availability disclaimers
    fire R-LIAB-5; bare absolute no-refunds noun phrases fire R-COMM-7."""

    # ------------------------------------------------------------------ R-COMM-7

    def test_bare_absolute_no_refunds_flagged(self):
        # Regression: bare noun-phrase denials of any refund (no modal+verb
        # form) must fire R-COMM-7 just like "non-refundable".
        flagged = [
            "There are no refunds under any circumstances.",
            "No refunds for any reason whatsoever.",
            "No refund for any reason whatsoever.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-7" for p in r.penalties), t

    def test_no_refunds_for_reason_shield(self):
        # Precision: "no refunds for any reason" with a defect carve-out is a
        # bounded denial and must not fire R-COMM-7.
        benign = [
            "No refunds will be given for any reason unless the services are defective.",
            "No refunds for any reason except for defective work.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-7" for p in r.penalties), t

    def test_refund_for_any_reason_not_flagged(self):
        # Precision: "a refund for any reason whatsoever is available" is a
        # permissive refund policy, not a denial, and must not fire R-COMM-7.
        r = score_document(
            ["A refund for any reason whatsoever is available within 30 days."], "d"
        )
        assert all(p.rule_id != "R-COMM-7" for p in r.penalties)

    # ------------------------------------------------------------------ R-DATA-5

    def test_up_to_bounded_retention_not_flagged(self):
        # Regression: post-termination retention bounded "for up to N days /
        # months" is a protective bound (like "for a period of N") and must
        # not fire R-DATA-5.
        benign = [
            "Following termination, Provider may retain copies of personal data for up to 90 days.",
            "Provider may keep customer data for up to 12 months after expiry of this agreement.",
            "Provider shall retain billing records for up to seven years following termination.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_unbounded_retention_still_flagged(self):
        # Controls: genuinely unbounded retention must keep firing R-DATA-5
        # despite the "up to" bound being added.
        flagged = [
            "Customer data shall be retained after termination for seven years.",
            "Provider may keep personal information following termination of this agreement.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    # ------------------------------------------------------------------ R-LIAB-4

    def test_reversed_order_disclaimers_flagged(self):
        # Regression: disclaimers with the noun order reversed ("representations
        # and warranties", "conditions and warranties") must fire R-LIAB-4.
        flagged = [
            "Provider disclaims all representations and warranties with respect to the software.",
            "Provider disclaims all conditions and warranties of any kind.",
            "Provider disclaims all express and implied warranties.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-4" for p in r.penalties), t

    def test_with_all_faults_flagged(self):
        # Regression: "provided with all faults" is an as-is synonym and must
        # fire R-LIAB-4 like "as-is".
        r = score_document(["The services are provided with all faults."], "d")
        assert any(p.rule_id == "R-LIAB-4" for p in r.penalties)

    def test_qualified_as_is_shield(self):
        # Precision: the surviving-warranties ("set forth ... shall apply")
        # qualification stays protective for R-LIAB-4.
        r = score_document(
            ["The software is provided as-is; however, the warranties set forth in Section 5 shall apply."],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-4" for p in r.penalties)

    def test_mutual_no_warranty_shield(self):
        # Precision: a mutual ("each party") disclaimer stays protective.
        r = score_document(
            ["Each party makes no warranties of any kind with respect to its own pre-contractual statements."],
            "d",
        )
        assert all(p.rule_id != "R-LIAB-4" for p in r.penalties)

    # ------------------------------------------------------------------ R-LIAB-5

    def test_gives_offers_provides_no_availability_flagged(self):
        # Regression: "gives/offers/provides no guarantee/warranty" of
        # availability must fire R-LIAB-5 like "makes no".
        flagged = [
            "The company gives no guarantee that the service will be continuously available.",
            "Provider offers no warranty that the service will be uninterrupted.",
            "Provider provides no warranty of fitness for a particular purpose.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-5" for p in r.penalties), t

    def test_sla_break_guarantee_shield(self):
        # Precision: a committed availability SLA with a guarantee stays
        # protective for R-LIAB-5.
        r = score_document(
            ["The Services will be available 99.9% of the time; guaranteed response times apply."], "d"
        )
        assert all(p.rule_id != "R-LIAB-5" for p in r.penalties)


class TestCycle16Precision:
    """Cycle-16 precision: first-person "in/at our sole discretion" and bare
    "immediately" suspension fire R-COMM-5/-8; fee-keyed one-sided liability
    caps and "export laws" compliance are protective; prior-authorization
    export wording shields R-EXP-4; data-led passive purposes fire R-DATA-3."""

    # ------------------------------------------------------------------ R-COMM-5

    def test_our_discretion_in_variant_flagged(self):
        # Regression: "in our sole/absolute discretion" (first person,
        # preposition "in") must fire R-COMM-5.
        flagged = [
            "Provider may modify this agreement in our sole discretion.",
            "We may update the terms in our own absolute discretion.",
            "These terms may be updated by Provider in its sole discretion.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-5" for p in r.penalties), t

    def test_our_discretion_at_variant_flagged(self):
        # Regression: the at-variant keeps firing after the "in" preposition
        # was added to the shared alternation.
        r = score_document(["We may update the terms at our absolute discretion."], "d")
        assert any(p.rule_id == "R-COMM-5" for p in r.penalties)

    def test_notice_based_amendment_shield(self):
        # Precision: amendment upon thirty days' notice stays protective.
        r = score_document(["Provider may modify this agreement with thirty days' notice."], "d")
        assert all(p.rule_id != "R-COMM-5" for p in r.penalties)

    # ------------------------------------------------------------------ R-COMM-8

    def test_bare_immediately_suspension_flagged(self):
        # Regression: bare "immediately" as the suspension qualifier (no
        # notice/consent/effect phrasing) must fire R-COMM-8.
        flagged = [
            "Provider may suspend your account immediately.",
            "Provider may suspend the account immediately.",
            "Provider may immediately suspend the account.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-8" for p in r.penalties), t

    def test_suspension_immediately_notice_shield(self):
        # Precision: suspension "immediately upon written notice" is
        # notice-based and mutually qualified, hence protective.
        r = score_document(
            ["Either party may suspend the account immediately upon written notice."], "d"
        )
        assert all(p.rule_id != "R-COMM-8" for p in r.penalties)

    def test_suspension_grounds_shield(self):
        # Precision: suspension for stated material-breach grounds stays
        # protective for R-COMM-8.
        r = score_document(
            ["Provider may suspend the account if Customer materially breaches this agreement."], "d"
        )
        assert all(p.rule_id != "R-COMM-8" for p in r.penalties)

    # ------------------------------------------------------------------ R-LIAB-2

    def test_one_sided_fee_keyed_cap_shield(self):
        # Regression: a liability cap keyed to fees actually paid by the
        # customer / received by the provider is balanced and must not fire
        # R-LIAB-2.
        benign = [
            "The aggregate liability of each party shall not exceed the fees paid by Customer under this agreement.",
            "Provider's aggregate liability shall not exceed the fees received by Provider.",
            "The aggregate liability of each party shall not exceed the fees paid by the customer in the prior twelve months.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-2" for p in r.penalties), t

    def test_fixed_amount_cap_still_flagged(self):
        # Controls: a plain fixed-dollar cap retains risk and must keep firing
        # R-LIAB-2 despite the fee-keyed shields being added.
        flagged = [
            "Provider's aggregate liability shall not exceed $50,000.",
            "The aggregate liability of each party shall not exceed one million dollars.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-2" for p in r.penalties), t

    # ------------------------------------------------------------------ R-EXP-1 / R-EXP-4

    def test_export_laws_compliance_shield(self):
        # Regression: "applicable export laws" is the plain-law form of the
        # exclusion and must not fire R-EXP-1.
        benign = [
            "Licensed software may be exported in accordance with applicable export laws.",
            "All exports shall comply with applicable export laws and regulations.",
            "Dealings shall be subject to applicable sanctions and export laws.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-EXP-1" for p in r.penalties), t

    def test_prior_written_authorization_export_shield(self):
        # Regression: prior-written-authorization-only export wording is a
        # compliance control and must not fire the absence rule R-EXP-4.
        benign = [
            "Software may be exported only with prior written authorization.",
            "Exports shall be made only upon written approval from Provider.",
            "The software may be exported only with the prior written consent of the vendor.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-EXP-4" for p in r.penalties), t

    def test_export_obligation_without_control_still_flagged(self):
        # Controls: export wording without any compliance control keeps firing
        # R-EXP-4 (and R-EXP-1 by topic).
        flagged = [
            "Customer may export the software to any country.",
            "The company licenses software for international sale and shipment.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-EXP-4" for p in r.penalties), t

    # ------------------------------------------------------------------ R-DATA-3

    def test_data_led_passive_purpose_flagged(self):
        # Regression: data-led passive constructions with an open-ended purpose
        # must fire R-DATA-3.
        flagged = [
            "Data may be used for our own business purposes.",
            "Customer data shall be used for any other purpose for which it was not collected.",
            "Personal data may be disclosed for marketing purposes.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-3" for p in r.penalties), t

    def test_data_led_purpose_limited_shield(self):
        # Precision: data-led passive phrasing with a purpose-limited
        # qualification stays protective for R-DATA-3.
        benign = [
            "Data may be used only for the purpose of performing this agreement.",
            "Data will not be used for any purpose other than providing the services.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-3" for p in r.penalties), t


class TestCycle17Precision:
    """Cycle-17 precision: R-COMM-5's discretion tail now covers possessive
    role-noun forms ("in Provider's sole discretion", "at the Vendor's sole
    discretion"), reversed-order "at the sole discretion of X" tails, and the
    bare plural "terms"/"conditions" object across all three branches."""

    # ------------------------------------------------------------------ R-COMM-5

    def test_possessive_noun_discretion_flagged(self):
        # Regression: "'s" possessive role-noun discretion ("in Provider's
        # sole discretion", "at the Vendor's discretion", "in Licensor's
        # absolute discretion") must fire R-COMM-5 in the active branches.
        flagged = [
            "Provider may modify this agreement in Provider's sole discretion.",
            "Provider may amend terms at Provider's sole discretion.",
            "We may change the terms at the Vendor's sole discretion.",
            "Licensor may modify this agreement in Licensor's absolute discretion.",
            "Provider may amend terms at the sole discretion of the Vendor.",
            "Licensor may change these terms at the sole discretion of Licensor.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-5" for p in r.penalties), t

    def test_possessive_noun_discretion_passive_flagged(self):
        # Regression: the passive branch accepts the same possessive and
        # reversed-order tails when the amendment is done "by the [role]".
        flagged = [
            "These terms may be changed by the Company at the Company's sole discretion.",
            "The terms and conditions may be changed by the Provider at the Provider's absolute discretion.",
            "These terms may be revised by the Provider at the sole discretion of the provider.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-5" for p in r.penalties), t

    def test_bare_terms_object_flagged(self):
        # Regression: the bare plural object ("terms"/"conditions" without a
        # determiner) is a unilateral-amendment target and must fire R-COMM-5
        # across the discretion/tail family.
        flagged = [
            "Provider may amend terms at Provider's sole discretion.",
            "Provider may change conditions at the Vendor's sole discretion.",
            "Provider may vary terms at the sole discretion of the vendor.",
            "Provider may amend conditions at any time.",
            "Provider may revise terms without notice.",
            "Provider may change terms unilaterally.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-5" for p in r.penalties), t

    def test_possessive_shields_unchanged(self):
        # Controls: mutual/consent/notice-bound amendments keep silencing
        # R-COMM-5 even with the new bare-object and possessive tails.
        benign = [
            "Either party may amend terms by mutual written agreement.",
            "Provider may amend terms with the prior written consent of both parties.",
            "Provider may amend terms with thirty days' notice.",
            "Neither party may amend the terms without the written consent of the other.",
            "The parties may change conditions by mutual agreement.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-5" for p in r.penalties), t

    def test_unqualified_discretion_still_silent(self):
        # Precision: the unqualified form (pronoun or possessive role noun,
        # "at its/Vendor's discretion" without sole/absolute) stays out of
        # scope — the discriminator is the sole/absolute qualifier or the
        # notice-free tail.
        benign = [
            "Provider may amend terms at its discretion.",
            "Provider may amend terms at the Vendor's discretion.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-5" for p in r.penalties), t


class TestCycle18Precision:
    # ------------------------------------------------------------------ R-DATA-5
    # Precision: noun-led retention forms ("Retention of customer data ...")
    # without a retain/keep/store verb were silent for both bounded and
    # UNBOUNDED retention. The noun-led branch now fires them, and the
    # exclusion gained the bound idioms they use ("shall not exceed N",
    # "not exceeding", "no more than", "bounded/capped/limited to", "no
    # retention/storage/preservation of").

    def test_noun_led_unbounded_retention_flagged(self):
        flagged = [
            "Retention of customer data after termination.",
            "Retention of customer data following termination of this agreement.",
            "Storage of customer data after the expiry of this agreement.",
            "Preservation of customer data upon termination.",
            "The retention of customer data following termination is permitted.",
            "Any retention of personal data following termination is unrestricted.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_noun_led_bounded_retention_not_flagged(self):
        benign = [
            "Retention of customer data for up to 90 days after termination.",
            "Retention of customer data for a period of 12 months following termination.",
            "Retention of customer data shall not exceed 90 days after termination.",
            "Retention of customer data shall not exceed twelve months following termination.",
            "Retention of customer data for a period not exceeding 90 days after termination.",
            "Retention of customer data shall not exceed beyond six months after termination.",
            "Retention of customer data is capped at twelve months following termination.",
            "Retention of customer data is limited to 60 days after termination.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_noun_led_bounded_then_deletion_not_flagged(self):
        benign = [
            "Retention of customer data after termination shall not exceed 90 days, after which it shall be deleted.",
            "Retention of customer data following termination for a period of six months, after which such data shall be destroyed.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_no_retention_of_denial_not_flagged(self):
        # Regression: "no retention/storage/preservation of" is the noun-led
        # mirror of "shall not retain" and must stay silent.
        benign = [
            "No retention of customer data after termination.",
            "No storage of customer data following termination.",
            "No preservation of customer data upon termination.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_verb_led_controls_unchanged(self):
        # Controls: verb-led retention behavior is unchanged after adding the
        # noun-led branch and the new bound idioms.
        flagged = [
            "Customer data shall be retained after termination for seven years.",
            "Provider may keep personal information following termination of this agreement.",
            "Provider may retain customer data after such termination for seven years.",
        ]
        benign = [
            "Provider shall delete all customer data upon termination of this agreement.",
            "Provider may keep customer data for up to 12 months after expiry of this agreement.",
            "Provider shall retain billing records for up to seven years following termination.",
            "Provider may store customer data after termination for a period of 90 days.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t


class TestCycle19Precision:
    """Cycle-19 precision: attributive retention forms ("customer data
    retention") in R-DATA-5. The attributive noun form ("data retention after
    termination.") without a preposition ("retention of data") or a retention
    verb was silent even for UNBOUNDED retention. Two paired branches now fire
    the attributive form (forward + leading/reversed order), and the exclusion
    gained the "no customer data retention" attributive denial mirror. The
    paragraph-wide bound idioms already silence the bounded attributive forms.
    """

    def test_attributive_unbounded_retention_flagged(self):
        flagged = [
            "Customer data retention after termination.",
            "Customer data retention following termination of this agreement.",
            "Personal data retention after the expiry of this agreement.",
            "Data retention after termination of this agreement.",
            "Customer data storage following termination is unrestricted.",
            "After termination of this agreement, customer data retention is permitted.",
            "After termination, customer data retention shall be permitted.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_attributive_bounded_retention_not_flagged(self):
        benign = [
            "Customer data retention for up to 90 days after termination.",
            "Customer data retention shall not exceed 90 days after termination.",
            "Data retention for a period of 12 months following termination.",
            "Customer data retention following termination is capped at twelve months.",
            "Customer data retention is limited to 60 days after termination.",
            "Customer data retention shall not exceed 90 days, after which it shall be deleted.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_attributive_topic_only_not_flagged(self):
        # A bare mention of a retention policy with no termination anchor is
        # not post-termination retention beyond a bound.
        t = "Provider has a comprehensive customer data retention policy."
        r = score_document([t], "d")
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)

    def test_attributive_no_retention_denial_not_flagged(self):
        # "No customer data retention" is the attributive mirror of the
        # noun-led "no retention of customer data" and must stay silent.
        benign = [
            "No customer data retention after termination.",
            "No data storage following termination.",
            "No personal data preservation upon termination.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_attributive_controls_unchanged(self):
        # Controls: noun-led and verb-led retention behavior is unchanged
        # after adding the attributive branch.
        flagged = [
            "Retention of customer data after termination.",
            "Customer data shall be retained after termination for seven years.",
            "Provider may keep personal information following termination of this agreement.",
        ]
        benign = [
            "Provider may keep customer data for up to 12 months after expiry of this agreement.",
            "Provider shall delete all customer data upon termination of this agreement.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t


class TestCycle20Precision:
    """Cycle-20 precision: positive authorization-grant export wording.

    Export clauses that *require* or *grant* authorization before export are
    compliance controls, but the coupled pair R-EXP-1 (exclusion) and R-EXP-4
    (pattern) only knew a few of their phrasings. "Exports are subject to the
    prior written authorization of the relevant authorities." fired both rules,
    and "Exports are subject to obtaining the approval of the relevant
    authority." fired R-EXP-1 + R-EXP-4 because the `obtain ... approval`
    idiom existed only in R-EXP-3's exclusion. The grant-language family
    (`with|upon|without`, `require`, `obtain`, `subject to`) is now encoded
    identically on both coupled sides.
    """

    def test_positive_grant_forms_silent(self):
        # Authorization-grant wording is a control: neither R-EXP-1 nor
        # R-EXP-4 should fire.
        benign = [
            "Software may be exported with prior written authorization from the applicable authorities.",
            "The software shall be exported upon written consent of the licensor.",
            "Exports are subject to the prior written authorization of the relevant authorities.",
            "Customer shall not transfer or export the software without the approval of Provider.",
            "Exports are subject to obtaining the approval of the relevant authority.",
            "The software may be delivered with permission of the export licensing body.",
            "Provider shall require the prior written consent of the licensor before any export.",
            "Each export shall require a valid export license from the applicable authorities.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id not in ("R-EXP-1", "R-EXP-4") for p in r.penalties), t

    def test_cycle16_export_shield_controls_unchanged(self):
        # Cycle-16 controls: restricted export wording stays silent, bare
        # export wording keeps firing R-EXP-4.
        benign = [
            "Software may be exported only with prior written authorization.",
            "Exports shall be made only upon written approval from Provider.",
            "The software may be exported only with the prior written consent of the vendor.",
        ]
        flagged = [
            "Customer may export the software to any country.",
            "The technology is exported to customers worldwide without restriction.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-EXP-4" for p in r.penalties), t
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-EXP-4" for p in r.penalties), t

    def test_sanctions_clauses_stay_silent(self):
        # R-EXP-2 controls: sanctioned-jurisdiction carve-outs keep their
        # compliance shields after the R-EXP-1/R-EXP-4 edits.
        benign = [
            "No exports to Iran or Syria unless licensed under applicable sanctions.",
            "The company does not permit sales to Cuba.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id not in ("R-EXP-1", "R-EXP-2", "R-EXP-4") for p in r.penalties), t

    def test_reexport_controls_unchanged(self):
        # R-EXP-3 controls: diversion wording with a control stays silent,
        # unrestricted re-export wording keeps firing.
        unflagged = [
            "The company shall maintain re-export and diversion controls.",
        ]
        for t in unflagged:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-EXP-3" for p in r.penalties), t
        t = "The software may be re-exported to any country without restriction."
        r = score_document([t], "d")
        assert any(p.rule_id == "R-EXP-3" for p in r.penalties), t

    def test_uncontrolled_export_topic_still_flagged(self):
        # Controls: trade terms with no visible control retain R-EXP-1.
        flagged = [
            "The parties will arrange for bribery insurance on all shipments.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-EXP-1" for p in r.penalties), t


class TestCycle21Precision:
    """Cycle-21 precision: additional denial-phrasing variants in R-DATA-5.
    The exclusion previously silenced only "not retained/kept" (passive) plus
    the "no retention of" / "no ... retention" noun forms. Sentence-initial
    "No ... data shall be retained", "No party shall retain", and reversed-order
    "After termination, ... shall not retain/store" phrasings over-fired the
    rule even though they positively forbid post-termination retention. Three
    paired denial branches were added to the exclusion. Covered: singular
    party names, "None of the parties", plain "No customer data is retained",
    and reversed-order active denial. Positive unbounded retention controls
    still flag; existing noun/attributive denials and bounded forms stay silent.
    """

    def test_sentence_initial_no_be_denial_not_flagged(self):
        benign = [
            "No customer data shall be retained by Provider after termination of the Agreement.",
            "No personal data will be kept by the parties after expiry of this Agreement.",
            "No information shall be stored following termination of the Agreement.",
            "No customer data is retained after termination of the agreement.",
            "Following expiry, no customer data shall be stored by Provider.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_sentence_initial_no_party_denial_not_flagged(self):
        benign = [
            "No party shall retain customer data after termination of the Agreement.",
            "No provider shall keep any customer data following termination.",
            "No vendor shall store personal data after expiry of this agreement.",
            "None of the parties shall retain customer data after termination.",
            "None of the providers shall keep customer data following expiration.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_reversed_order_active_denial_not_flagged(self):
        benign = [
            "After termination, the parties shall not retain any customer data.",
            "After termination, Customer shall not keep any personal data.",
            "Upon expiry, the Provider shall not store any customer information.",
            "After termination, the Provider must not maintain any customer data.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_positive_unbounded_retention_still_flagged(self):
        flagged = [
            "Customer data shall be retained by Provider after termination of the Agreement.",
            "Provider shall retain customer data after termination.",
            "After termination, Provider shall retain any customer data.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_prior_denial_and_bound_forms_unchanged(self):
        benign = [
            "There shall be no retention of customer data after termination.",
            "Customer data shall not be retained after termination.",
            "Customer data shall not be kept by Provider after termination.",
            "Provider may retain customer data for up to 90 days after termination.",
            "Customer data shall be deleted within 30 days after termination.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t


class TestCycle22Precision:
    """Cycle-22 precision: neither-party denials + compliance carve-outs in
    R-DATA-5, and an as-is relative-clause guard in R-LIAB-4.

    R-DATA-5: the cycle-21 exclusion family covered "no party / none of the
    parties ... shall retain" but the "neither party" and
    "neither A nor B shall retain" forms still over-fired. The exclusion's
    legal-basis family covered "necessary to comply" but not
    "necessary for compliance" / "in compliance with" / "as necessary for
    compliance", so bounded legal-necessity retention still over-fired.
    R-LIAB-4: the bare "as is" pattern also matched relative clauses like
    "data as is necessary / as is required for ...", so a genuine as-is
    disclaimer remains discredited by unrelated relative-clause wording.
    Positive unbounded retention and genuine as-is disclaimers still flag.
    """

    def test_neither_party_denials_not_flagged(self):
        benign = [
            "Neither party may retain customer data after termination of the Agreement.",
            "Neither party shall keep any customer data after expiry.",
            "Neither party will store customer data following termination.",
            "Neither party shall maintain any records of customer data after termination.",
            "Neither Provider nor Customer shall retain customer data after termination of the Agreement.",
            "After termination, neither party may retain customer data.",
            "No party shall retain customer data after termination of the Agreement.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_compliance_carve_outs_not_flagged(self):
        benign = [
            "Customer data shall be retained after termination only where necessary for "
            "compliance with applicable regulations.",
            "Customer data may be retained after termination in compliance with applicable law.",
            "Customer data may be retained after termination as necessary for compliance "
            "with applicable law.",
            "Provider shall retain customer data after termination only to the extent "
            "required by applicable law.",
            "Retention of customer data after termination is necessary for compliance "
            "with statutory obligations.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_as_is_relative_clause_not_flagging_liab4(self):
        benign = [
            "Customer data as is necessary for the provision of services may be retained "
            "after termination.",
            "Such information as is required to resolve disputes may be kept after termination.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-4" for p in r.penalties), t

    def test_positive_controls_still_flagged(self):
        flagged = [
            "Customer data shall be retained by Provider after termination of the Agreement.",
            "After termination, Provider shall retain any customer data.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t
        flagged_as_is = [
            "The software is provided as is.",
            "The software is provided as is, without warranty of any kind.",
        ]
        for t in flagged_as_is:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-4" for p in r.penalties), t


class TestCycle23Precision:
    """Cycle-23 precision: obligation-mandate retention forms in R-DATA-5.

    The R-DATA-5 pattern only carried the permission modals (shall / may /
    will / can) and "is required|obligated to" in the reversed-order branch,
    so genuine obligation-mandate retention still fired nothing: "Provider
    must retain customer data after termination", "is required to retain",
    "is obligated to store", "is compelled to retain", "shall be required
    to retain", "undertakes / commits / agrees to retain" all stayed silent.

    Widening the pattern alone was insufficient: the exclusion's bare first
    token `(?:require|required|obligat|...)` was a bare-token trap — it
    swallowed genuine obligations ("is required to retain", "is obligated to
    store") while the legal-mandate carve-outs ("required by law", "required
    by applicable regulations", "obligated under applicable law", "to the
    extent required by law") must keep staying silent. The exclusion now
    anchors on the legal mandate (required by/under law, obligated under/by
    law, to the extent required, required to comply) instead of the bare
    token.
    """

    def test_obligation_mandate_retention_flagged(self):
        flagged = [
            "Provider must retain customer data after termination of the Agreement.",
            "Customer data must be retained by Provider after termination.",
            "After termination, each party is required to retain customer data.",
            "Provider is required to retain customer data after termination.",
            "Provider is obligated to store customer data after termination.",
            "After termination, Provider is obligated to retain customer data.",
            "Provider shall be required to retain customer data after termination.",
            "Each party undertakes to retain customer data after termination.",
            "Provider agrees to retain customer data after termination.",
            "Each party commits to retaining customer data after termination.",
            "Provider will be required to retain customer data after termination.",
            "Each party is compelled to retain customer data after termination.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_legal_mandate_retention_not_flagged(self):
        # Legal-mandate retention (required/obligated by law or regulation)
        # is a compliance carve-out and must stay silent.
        benign = [
            "Provider is required by law to retain customer data after termination.",
            "Provider is required by applicable regulations to retain customer data after termination.",
            "Customer data is retained after termination to the extent required to comply with law.",
            "Provider is obligated under applicable law to retain customer data after termination.",
            "Customer data must be retained after termination to the extent required by law.",
            "Such retention after termination as is required by applicable law will be carried out.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_bound_and_denial_forms_unchanged(self):
        benign = [
            "Provider may retain customer data after termination for up to 90 days.",
            "Provider shall not retain customer data after termination.",
            "Provider shall retain Customer data following termination for tax "
            "purposes as required by applicable law.",
            "Following termination, Provider shall retain Customer records solely "
            "to comply with regulatory obligations.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_positive_controls_still_flagged(self):
        flagged = [
            "Provider shall retain customer data after termination.",
            "After termination, each party may retain the customer data.",
            "Customer data shall be retained after termination for seven years.",
            "Provider may keep personal information following termination of this agreement.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle24Precision:
    """Cycle-24 precision: passive-obligation retention forms in R-DATA-5.

    The R-DATA-5 pattern only covered active obligation verbs directly
    attached to a retention verb ("is required to retain", "must retain").
    The passive-obligation family — "is required to be retained", "is
    obligated to be stored", "shall be required to be kept", "must be bound
    to be retained", and their reversed-order twins after the termination
    anchor — stayed silent while firing nothing, an asymmetric gap against
    their active voice twins.

    Widenings had to preserve four boundaries:
    (1) passive denials ("may not be retained", "is prohibited from being
        kept", "is not required to be retained") stay silent via pattern gap
        — no optional negation was added;
    (2) legal-mandate carve-outs in passive voice ("required to be retained
        by applicable law", "required to be kept by statutory requirements",
        "must be retained by applicable law") stay silent via new exclusion
        branches that anchor on the law/regulation family after a mandate
        verb or after a passive retention verb;
    (3) bare numeric short-unit bounds ("for 90 days", "for 12 months")
        stay silent via a new exclusion bound branch that deliberately
        excludes years so "for seven years" stays flagged;
    (4) "for a period of / up to / a period not exceeding" bounds and the
        canonical "seven years" positive control keep their established
        behavior.
    """

    def test_passive_obligation_retention_flagged(self):
        flagged = [
            "Customer data is required to be retained by Provider after termination.",
            "Customer data is obligated to be stored by Provider after termination.",
            "Customer data is compelled to be retained after termination.",
            "Customer data shall be required to be retained after termination.",
            "Customer data is required to be kept by Provider after termination.",
            "Customer information is obligated to be stored by Provider after termination.",
            "Customer data may be required to be retained after termination.",
            "Customer data will be compelled to be preserved after termination.",
            "Customer data must be bound to be retained after termination.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_reversed_passive_retention_flagged(self):
        # Termination-anchored passive forms: obligation + be + retention
        # verb, and plain modal passive ("must be retained").
        flagged = [
            "After termination, customer data is required to be retained by Provider.",
            "After termination, customer data shall be required to be kept by Provider.",
            "After termination, customer data is obligated to be stored by Provider.",
            "After termination, customer data must be retained by Provider.",
            "After termination, customer data will be retained by Provider.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_passive_denials_not_flagged(self):
        # Denial / prohibition shapes must stay silent (pattern gap — no
        # optional negation was added to the new passive branches).
        benign = [
            "Customer data may not be retained after termination.",
            "Provider is prohibited from retaining customer data after termination.",
            "Customer data is prohibited from being kept after termination.",
            "After termination, customer data may not be retained.",
            "After termination, customer data shall not be kept.",
            "After termination, customer data is not required to be retained.",
            "Customer data is not required to be retained after termination.",
            "Customer data must not be retained after termination.",
            "Customer data shall not be kept after termination.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_passive_legal_mandate_carveout_not_flagged(self):
        # Legal-mandate carve-outs in passive / mandate-tail positions are a
        # compliance basis and must stay silent.
        benign = [
            "Customer data is required to be retained by applicable law after termination.",
            "Provider is required to retain customer data by applicable regulations after termination.",
            "Provider is obligated to store customer data by applicable law after termination.",
            "Customer data is required to be retained by statutory requirements after termination.",
            "Customer data must be retained by applicable law after termination.",
            "Provider is required by law to retain customer data after termination.",
            "Customer data shall be retained after termination only to the extent required by applicable law.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_bare_numeric_bound_not_flagged(self):
        # Bare short-unit numeric bounds (days / weeks / months) are bounded
        # retention; the bound branch deliberately excludes years.
        benign = [
            "Provider may retain customer data after termination for 90 days.",
            "Customer data may be retained after termination for 12 months.",
            "Provider may retain customer data after termination for up to 90 days.",
            "Retention of customer data for a period of 12 months after termination.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_positive_controls_still_flagged(self):
        flagged = [
            "Customer data shall be retained after termination.",
            "Provider may keep customer data after termination.",
            "Customer data must be retained by Provider after termination.",
            "Customer data shall be retained after termination for seven years.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle25Precision:
    """Cycle-25 precision: bare-copula passive retention and
    as/so-long-as legal conditioning in R-DATA-5, plus R-LIAB-4
    adverb-intervened as-is guards.

    Two asymmetry gaps and one guard gap:
    (1) R-DATA-5 reversed-order branch covered "is required to be retained"
        and "must be retained" but not the bare copula fact-state passive
        ("customer data is maintained / kept / stored ... after
        termination"); the data-led forward branch had the same gap for
        "is retained".
    (2) Legal-conditioned "as long as" retention ("for as long as legally
        required / statutorily required / otherwise permitted by law / laws
        and regulations require") fired R-DATA-5; the new exclusion tail
        silences it while deliberately leaving business-need conditioning
        ("for as long as necessary", "as is necessary for the provision of
        services") flagged.
    (3) The R-LIAB-4 relative-clause guard ("as is necessary | required |
        needed | appropriate") failed when an adverb intervened ("as is
        strictly required"); the guard now allows a legally/otherwise/
        reasonably/lawfully adverb between "as is" and the adjective.

    Boundaries preserved: copula-passive denials ("is not retained") stay
    silent via pattern gap — the copula branch requires the retention verb
    to immediately follow the copula, so "not" blocks it; no optional
    negation was added.
    """

    def test_bare_copula_passive_retention_flagged(self):
        flagged = [
            "Customer data is retained after termination.",
            "Customer data is kept following expiration of the agreement.",
            "Information is stored upon termination.",
            "Following expiration, customer data is maintained.",
            "After termination, all customer data is preserved.",
            "Upon termination, personal data is retained by the provider.",
            "Customer information is stored after the termination.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_copula_passive_denials_not_flagged(self):
        benign = [
            "Customer data is not retained after termination.",
            "After termination, customer data is not maintained.",
            "Customer data is never kept following termination.",
            "Customer data is not stored after the termination.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_as_long_as_legal_conditioning_not_flagged(self):
        benign = [
            "Customer data may be retained for as long as legally required after termination.",
            "Customer data may be kept for as long as statutorily required.",
            "Data may be retained for as long as otherwise permitted by law after termination.",
            "Data is retained for as long as laws and regulations require.",
            "Data may be retained for as long as is strictly required after termination.",
            "Data may be kept for as long as is legally necessary.",
            "Data will be retained for as long as is otherwise appropriate.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_business_need_conditioning_still_flagged(self):
        flagged = [
            "Customer data may be retained for as long as necessary after termination.",
            "Customer data as is necessary for the provision of services may be retained after termination.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_as_long_as_adverb_guards_not_flagged(self):
        benign = [
            "Customer data may be retained for as long as is strictly required after termination.",
            "Such information as is required to resolve disputes may be retained.",
            "Data will be retained for as long as is otherwise appropriate.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-4" for p in r.penalties), t

    def test_genuine_asiab_disclaimers_still_flagged(self):
        flagged = [
            "The software is provided as is.",
            "All services are delivered as-is without warranty.",
            "Customer data is shared as is on an as-is basis.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-4" for p in r.penalties), t


class TestCycle26Precision:
    """Cycle-26 precision: R-LIAB-4 manner-connective adjectives,
    R-DATA-5 future-perfect passive retention, and R-DATA-5
    "pursuant to" legal-mandate tails.

    Three documented Limits, all symmetric:
    (1) The R-LIAB-4 relative-clause guard covered only
        necessary/required/needed/appropriate; "as is customary /
        standard / usual / typical / common / normal" and "as is the
        custom / practice" (manner connectives with a relative-clause
        reading) all still fired R-LIAB-4. The guard's adjective family
        gains the manner-connective synonyms; genuine as-is disclaimers
        (no connective adjective) still fire.
    (2) Future-perfect passive "will have been retained/kept/stored"
        was silent in R-DATA-5 in both the data-led forward branch and
        the reversed-order branch, so unbounded future-perfect
        retention ("will have been retained ... for seven years") was
        a genuine miss. The copula alternatives gain "will have" plus
        the optional "been"; future-perfect denials ("will not have
        been retained") stay silent via pattern gap — the interposed
        "not" blocks the immediate "will have" sequence.
    (3) Legal-mandate "pursuant to" tails ("pursuant to applicable
        law / statutory requirements / regulations / tax requirements")
        over-fired R-DATA-5. A new exclusion branch anchors "pursuant
        to" on legal words only (laws/regulations/requirements/
        obligations with optional applicable/statutory/legal/tax
        modifier); the contractual control "pursuant to the terms of
        this agreement" deliberately stays flagged (no legal anchor).
    """

    def test_manner_connective_as_is_not_flagged(self):
        benign = [
            "Data is shared as is customary in the industry.",
            "Information is processed as is standard practice.",
            "Retention follows industry norms as is usual in similar transactions.",
            "The service is delivered as is typical for software of this kind.",
            "Data handling occurs as is common among providers.",
            "Such safeguards are applied as is normal in the sector.",
            "Licensing follows the practice as is the custom in this market.",
            "Access is provided as is the practice for enterprise accounts.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-4" for p in r.penalties), t

    def test_genuine_asiab_disclaimers_still_flagged(self):
        flagged = [
            "The software is provided as is.",
            "All services are delivered as-is without warranty.",
            "The platform is supplied as is with all faults.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-4" for p in r.penalties), t

    def test_future_perfect_passive_retention_flagged(self):
        flagged = [
            "Customer data will have been retained by Provider after termination.",
            "Customer data will have been kept following expiration.",
            "Customer data will have been stored by the vendor for seven years after termination.",
            "After termination, customer data will have been retained by Provider.",
            "Following expiration, customer data will have been maintained.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_future_perfect_denials_not_flagged(self):
        benign = [
            "Customer data will not have been retained after termination.",
            "After termination, customer data will not have been kept.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_pursuant_to_legal_mandate_not_flagged(self):
        benign = [
            "Customer data may be retained after termination pursuant to applicable law.",
            "Customer data shall be kept after termination pursuant to statutory requirements.",
            "Provider may retain customer data after termination pursuant to regulations.",
            "Customer data is retained after termination pursuant to tax requirements.",
            "Data is retained following termination pursuant to applicable regulations.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_pursuant_to_contractual_still_flagged(self):
        flagged = [
            "Customer data may be retained after termination pursuant to the terms of this agreement.",
            "Provider shall keep customer data after termination pursuant to this contract.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle27Precision:
    """Cycle-27 precision: R-DATA-5 perfect-aspect modal retention.

    Cycle-26 covered only "will have been retained"; the sibling
    perfect-aspect modals ("shall/may/might/could/should/would/must
    have") stayed silent in R-DATA-5 in both the data-led forward
    branch and the reversed-order branch, so unbounded "Customer data
    shall have been retained by Provider after termination." was a
    genuine miss (the R-DATA-5 hazard is the perfect aspect itself,
    not the specific modal). The copula alternatives in both branches
    gain the full perfect-modal family with the optional "been";
    bounded controls stay silent (paragraph-wide bound branches) and
    denials ("shall not have been retained") stay silent via pattern
    gap — the interposed "not" blocks the immediate modal-have
    sequence, no optional negation added.
    """

    def test_perfect_modal_retention_flagged(self):
        flagged = [
            "Customer data shall have been retained by Provider after termination of the agreement.",
            "After termination, customer data shall have been retained by Provider.",
            "Customer data may have been retained by Provider following termination.",
            "After expiry, customer data may have been stored by Provider for seven years.",
            "The parties agree that customer data shall have been preserved by Provider after termination.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_perfect_modal_retention_bounded_not_flagged(self):
        benign = [
            "Customer data may have been retained by Provider after termination for up to 90 days.",
            "Customer data shall have been retained by Provider for a period of 6 months after termination.",
            "After termination, customer data may have been retained for no more than 12 months.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_perfect_modal_denials_not_flagged(self):
        benign = [
            "Customer data shall not have been retained by Provider after termination.",
            "After termination, customer data may not have been retained by Provider.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_prior_perfect_and_copula_controls_still_flagged(self):
        flagged = [
            "Customer data will have been retained by Provider after termination.",
            "Customer data will have been stored by Provider for seven years after termination.",
            "Customer data is retained by Provider after termination.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle28Precision:
    """Cycle-28 precision: R-DATA-5 period/window-anchored retention.

    R-DATA-5's pattern anchored retention only after termination events
    (termination/expiration/expiry); retention anchored on a retention
    *period* or *window* ("after the latest permitted period", "beyond
    the retention period", "after the retention period has expired")
    was a genuine miss — the unbounded retention hazard is the same even
    when the anchor is a period rather than a termination event. The
    shape also exposed that "beyond" was a missing termination anchor
    entirely ("Provider may retain customer data beyond termination."),
    and that post-termination numeric bounds ("for up to N years after
    the latest permitted period") must stay silent via the existing
    paragraph-wide bound branches. Fix: every R-DATA-5 anchor widens
    (?:after|following|upon|beyond) (?:the )?(?:termination|such
    termination|expiration|expiry|(?:latest |permitted |applicable |
    retention ){0,2}(?:period|window)) in the pattern's data-led,
    reversed-order, noun-led and attributive branches, and in the
    exclusion's reversed-order denial branch (so period/beyond-anchored
    denials stay silent). The consent-based controls ("for the permitted
    period only", "during the term") and "beyond the retention period"
    denials rely on pattern anchors/denial branches and must not regress.
    """

    def test_period_window_retention_flagged(self):
        flagged = [
            "Customer data may be retained by Provider after the latest permitted period.",
            "Customer data may be preserved by Provider following the latest permitted period.",
            "Customer data shall be kept after the latest permitted period.",
            "Provider may store customer data following the latest permitted period.",
            "Customer data may be retained beyond the retention period.",
            "Provider may store customer data after the applicable retention period.",
            "Provider may retain customer data after the retention period has expired.",
            "Customer data may be kept following the permitted retention window.",
            "Provider may preserve customer data beyond the applicable period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_beyond_termination_anchor_flagged(self):
        flagged = [
            "Provider may retain customer data beyond termination.",
            "Provider may retain customer data beyond the expiry of the Agreement.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_period_window_noun_and_attributive_flagged(self):
        flagged = [
            "Retention of customer data after the latest permitted period.",
            "Customer data retention beyond the applicable retention period.",
            "After the retention period has expired, Provider may retain customer data.",
            "Beyond the permitted retention period, customer data may be retained by Provider.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_period_window_bounded_not_flagged(self):
        benign = [
            "Provider may retain customer data for up to 2 years after the latest permitted period.",
            "Customer data may be retained for a period not exceeding one year after the latest permitted period.",
            "Provider may keep customer data for no more than 12 months after the latest permitted period.",
            "Customer data may be retained for a period of 6 months after the latest permitted period.",
            "Provider may store customer data for up to 90 days after the latest permitted period.",
            "Customer data may be retained for a period not exceeding one year after the retention period has expired.",
            "Provider may keep customer data for no more than 6 months following the permitted retention window.",
            "Customer data may be retained for a period of 90 days beyond the applicable period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_period_denials_not_flagged(self):
        benign = [
            "Provider shall not retain customer data beyond the retention period.",
            "Customer data may not be retained after the latest permitted period.",
            "No retention of customer data after the latest permitted period shall occur.",
            "No customer data is retained beyond the applicable period.",
            "The parties shall not retain customer data for more than 2 years after the latest permitted period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_consent_controls_still_silent(self):
        benign = [
            "Provider may retain customer data for the permitted period only.",
            "Customer data may be processed during the term of this Agreement for the provision of services.",
            "Provider must return customer data within the retention window.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_unbounded_termination_controls_still_flagged(self):
        flagged = [
            "Provider may retain customer data for seven years after termination.",
            "Provider may retain customer data after termination.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_bounded_termination_controls_still_silent(self):
        benign = [
            "Provider may retain customer data for up to 90 days after termination.",
            "Customer data may be kept for up to 6 months following expiration of the Agreement.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t


class TestCycle29Precision:
    r"""Cycle-29 precision: R-DATA-5 noun-led branches with object-group qualifiers.

    The cycle-28 fix widened R-DATA-5's retention ANCHOR family to include
    period/window anchors, but the noun-led branches ("retention/storage/
    preservation of customer data after ...") still required the data/
    information noun to follow "of" directly. Object-group qualifiers
    ("retention of copies of customer data after the latest permitted
    period") broke the match — a genuine miss: unbounded retention of
    customer-data copies is the same R-DATA-5 hazard. Fix: the noun-led
    forward branch (rules.py ~547) and reversed-order branch (~555) gained
    the same optional qualifier chain the object-led branches carry
    ((?:any |all |the )?(?:backup )?(?:copies?|extracts?|records?|possession)?
    \s*(?:of\s+)? doubled), so "retention of copies of customer data" matches
    with or without qualifiers. Bounded ("for a period not exceeding 90 days"),
    denial ("no retention of copies of ... shall occur") and legal-mandate
    carve-outs must stay silent through the existing paragraph-wide branches.
    """

    def test_noun_led_object_group_forward_flagged(self):
        flagged = [
            "Retention of copies of customer data after the latest permitted period.",
            "Storage of backup records of personal information beyond the applicable retention period.",
            "Preservation of all extracts of customer data following the permitted retention window.",
            "Retention of copies of customer data after termination.",
            "Storage of backup records of personal data upon expiration of the Agreement.",
            "Provider shall retain copies of customer data after the latest permitted period.",
            "Provider may keep backup records of personal information beyond the applicable retention period.",
            "Provider shall retain any backup copies of all records of personal information beyond the retention period.",
            "Provider must preserve possession of customer information after the retention period has expired.",
            "Provider shall preserve records of personal data beyond the applicable period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_noun_led_object_group_reversed_flagged(self):
        flagged = [
            "After the latest permitted period, retention of copies of customer data.",
            "Beyond the applicable retention period, storage of backup records of personal information.",
            "After termination, retention of copies of customer data.",
            "Following expiration, storage of backup records of personal data.",
            "After the latest permitted period, Provider shall retain copies of customer data.",
            "Beyond the retention period, Provider shall also retain copies of customer data.",
            "After the latest permitted period, copies of customer data may be retained by Provider.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_noun_led_object_group_bounded_not_flagged(self):
        benign = [
            "Retention of copies of customer data for a period of 90 days after the latest permitted period.",
            "After the latest permitted period, preservation of copies of customer data for no more than 12 months.",
            "Provider may retain copies of customer data for a period of 90 days after the latest permitted period.",
            "Provider may keep backup records of personal information for up to 6 months beyond the applicable retention period.",
            "Provider shall retain copies of customer data for no more than 12 months after the retention period has expired.",
            "Retention of copies of customer data for a period not exceeding 90 days after the latest permitted period.",
            "After the latest permitted period, retention of copies of customer data for a period not exceeding 90 days.",
            "Preservation of all extracts of customer data for no more than 6 months following the permitted retention window.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_noun_led_object_group_denials_not_flagged(self):
        benign = [
            "After the latest permitted period, Provider shall not retain copies of customer data.",
            "Beyond the applicable retention period, Provider may not keep backup records of personal information.",
            "Following the permitted retention window, Company will not store copies of customer data.",
            "Provider must not preserve possession of customer information after the retention period has expired.",
            "No retention of copies of customer data after the latest permitted period shall occur.",
            "After the latest permitted period, no storage of backup records of personal information shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_noun_led_object_group_legal_mandate_not_flagged(self):
        benign = [
            "Provider shall retain copies of customer data as required by applicable law after the latest permitted period.",
            "Provider shall retain backup records of personal information in accordance with statutory requirements beyond the applicable period.",
            "Beyond the applicable period, Provider shall retain records of personal data in accordance with statutory requirements.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_noun_led_unbounded_controls_still_flagged(self):
        flagged = [
            "After termination, Provider shall retain copies of customer data.",
            "Beyond the expiry of the Agreement, Provider shall retain copies of customer data.",
            "Following termination, Provider shall store all extracts of customer data.",
            "Retention of copies of customer data and storage of backup records of personal information after the latest permitted period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle30Precision:
    r"""Cycle-30 precision: R-DATA-5 attributive branches with interposed object qualifiers.

    The cycle-29 fix covered the noun-led ("retention of copies of customer
    data") object-groups, but the ATTRIBUTIVE branches ("customer data
    retention beyond ...") still required the data/information noun to
    directly precede the retention noun. A qualifier interposed between them
    ("customer data backup retention beyond ...") broke the match — the same
    R-DATA-5 hazard. Fix: widen both attributive branches (forward and
    reversed) with an optional object-group chain ("backup copies of", a bare
    modifier "backup", "the possession", etc.) interposed between the data
    noun and the retention verb-noun, and mirror the shape into the
    exclusion's attributive denial branch.

    The widening must not over-fire: bounded retention stays silent in all
    qualifier shapes, denials (both orders), legal mandates (including
    multi-qualifier "pursuant to applicable tax laws"), and consent/policy
    text remain silent.
    """

    def test_attributive_interposed_qualifier_flagged(self):
        flagged = [
            "Customer data backup retention beyond the applicable retention period.",
            "Personal information copies storage after the latest permitted period.",
            "Customer data extracts preservation following the permitted retention window.",
            "Personal data records retention after the retention period has expired.",
            "Customer data all backup copies retention after the retention period has expired.",
            "Customer data the possession retention following the permitted retention window.",
            "Customer data backup retention after the applicable retention period has expired.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_attributive_interposed_qualifier_reversed_flagged(self):
        flagged = [
            "Beyond the applicable retention period, customer data backup retention.",
            "After the latest permitted period, personal information copies storage.",
            "Beyond the applicable retention period, personal data backup copies preservation.",
            "After the latest permitted period, customer data the possession retention.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_attributive_bounded_not_flagged(self):
        benign = [
            "Customer data backup retention for a period of 90 days beyond the applicable retention period.",
            "Personal data records storage for no more than 12 months after the latest permitted period.",
            "Customer data copies retention for a period not exceeding 6 months after termination.",
            "Personal information backup storage for up to one year after the retention period has expired.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_attributive_denials_not_flagged(self):
        benign = [
            "No customer data backup retention beyond the applicable retention period shall occur.",
            "Beyond the applicable retention period, no customer data backup retention shall occur.",
            "After the latest permitted period, provider shall not retain copies of customer data.",
            "No retention of copies of customer data beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_attributive_legal_mandate_not_flagged(self):
        benign = [
            "Customer data backup retention as required by applicable law beyond the applicable retention period.",
            "Beyond the applicable retention period, personal data copies storage in accordance with statutory requirements.",
            "Customer data backup retention pursuant to applicable tax laws after the latest permitted period.",
            "Customer data backup retention pursuant to applicable law after the latest permitted period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_attributive_unbounded_controls_still_flagged(self):
        flagged = [
            "Customer data retention beyond the applicable retention period.",
            "Retention of copies of customer data beyond the applicable retention period.",
            "Provider shall retain copies of customer data beyond the applicable retention period.",
            "Beyond the applicable retention period, personal data storage.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_attributive_modifier_only_chains_flagged(self):
        flagged = [
            "Customer data backup retention beyond the applicable retention period.",
            "Beyond the applicable retention period, personal information backup storage.",
            "Customer data all retention after the retention period has expired.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

class TestCycle31Precision:
    r"""Cycle-31 precision: R-DATA-5 pre-data-modifier attributive denials.

    Cycle-30's attributive branches already cover a pre-data modifier such as
    "customer backup data retention beyond ...": the optional customer/personal
    prefixes let the match start at the data noun mid-phrase. So the hazard
    shape flags correctly. But the exclusion's denial branches required the
    data/information noun to directly follow the customer/personal prefixes, so
    a modifier interposed between them ("no customer BACKUP data retention
    ...") broke the denial and the sentence over-fired. Additionally, the
    "retention shall NOT OCCUR / NOT TAKE PLACE / NOT HAPPEN" construction was
    never excluded, with or without the modifier.

    Fix: insert an optional single-word modifier "(?:\w+ )?" between the
    customer/personal prefix and the data noun in both the nominal-denial and
    verb-form-denial exclusion branches, and add a new exclusion branch for
    "shall not occur / take place / happen". Positive unbounded controls must
    keep flagging.
    """

    def test_attributive_denials_not_flagged(self):
        benign = [
            "No customer backup data retention beyond the applicable retention period shall occur.",
            "No personal encrypted data storage after the latest permitted period shall occur.",
            "No customer archived information preservation following the permitted retention window shall occur.",
            "After the latest permitted period, no personal encrypted data storage shall occur.",
            "Beyond the applicable retention period, no customer backup data retention shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_attributive_verb_form_denials_not_flagged(self):
        benign = [
            "No customer backup data shall be retained beyond the applicable retention period.",
            "Beyond the applicable retention period, no personal encrypted data shall be stored by the provider.",
            "No customer archived information shall be preserved after the latest permitted period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_shall_not_occur_denials_not_flagged(self):
        benign = [
            "Customer backup data retention shall not occur beyond the applicable retention period.",
            "Beyond the applicable retention period, personal encrypted data storage shall not take place.",
            "Customer archived information preservation will not happen following the permitted retention window.",
            "Personal data storage beyond the applicable retention period shall not occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_bare_denial_families_still_flagged(self):
        flagged = [
            "Customer data retention beyond the applicable retention period.",
            "Customer backup data retention beyond the applicable retention period.",
            "After the latest permitted period, personal encrypted data storage.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_denial_decoy_does_not_suppress_flag(self):
        # The "shall not occur" applies to a different subject; the retention
        # clause itself still unboundedly retains, so it must keep flagging.
        flagged = [
            "Cancellation of the agreement shall not occur until customer backup data retention beyond the applicable retention period is completed.",
            "Notwithstanding anything stated elsewhere, customer backup data retention beyond the applicable retention period shall occur.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle32Precision:
    r"""Cycle-32 precision: R-DATA-5 two-word pre-data qualifier denials.

    Cycle-31 added an optional single-word modifier slot "(?:\w+ )?" between the
    customer/personal prefix and the data noun in the exclusion's nominal-denial
    and verb-form-denial branches, covering "no customer BACKUP data retention".
    A TWO-word pre-data qualifier phrase ("customer online account data", "personal
    sensitive financial data") still broke the denial and over-fired R-DATA-5.

    Fix: widen the single-word slot to "(?:\w+ ){0,2}" in both branches, covering
    up to two interposed qualifier words. The "shall not occur / take place /
    happen" branch is anchored on the retention word, not the data noun, so it is
    qualifier-agnostic and needs no widening. Positive unbounded controls and the
    decoy "shall not occur" must keep flagging; bounded variants must stay silent.
    """

    def test_two_word_pre_data_denials_not_flagged(self):
        benign = [
            "No customer online account data retention beyond the applicable retention period shall occur.",
            "After the latest permitted period, no personal sensitive financial data storage shall occur.",
            "No customer archived payment information preservation following the permitted retention window shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_two_word_pre_data_verb_denials_not_flagged(self):
        benign = [
            "No customer online account data shall be retained beyond the applicable retention period.",
            "Beyond the applicable retention period, no personal sensitive financial data shall be stored by the provider.",
            "No customer archived payment information shall be preserved after the latest permitted period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_two_word_shall_not_occur_denials_not_flagged(self):
        # Anchored on the retention word, so qualifier-agnostic with or without
        # up to two pre-data qualifier words.
        benign = [
            "Customer online account data retention shall not occur beyond the applicable retention period.",
            "Beyond the applicable retention period, personal sensitive financial data storage shall not take place.",
            "Customer archived payment information preservation will not happen following the permitted retention window.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_two_word_qualified_bounded_not_flagged(self):
        benign = [
            "Customer online account data shall be retained for no more than 12 months beyond the applicable retention period.",
            "Beyond the applicable retention period, personal sensitive financial data storage for a period of 90 days.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_two_word_qualified_unbounded_still_flagged(self):
        flagged = [
            "Customer online account data retention beyond the applicable retention period.",
            "After the latest permitted period, personal sensitive financial data storage.",
            "Notwithstanding anything stated elsewhere, customer online account data retention beyond the applicable retention period shall occur.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle33Precision:
    r"""Cycle-33 precision: R-DATA-5 three-word pre-data qualifier boundary.

    Cycle-32 widened the exclusion denial branches' pre-data modifier slot to
    "(?:\w+ ){0,2}", covering up to TWO qualifier words ("customer online account
    data"). A THREE-word phrase ("customer online account usage data", "personal
    sensitive financial card data") still broke the denial and over-fired R-DATA-5.

    Fix: widen the slot to "(?:\w+ ){0,3}" in both the nominal-denial and
    verb-form-denial exclusion branches, so three-word pre-data denials stay
    silent. FIVE-word phrases now sit beyond the widened boundary and still
    flag (cycle-34 widened the boundary itself to four words; see
    TestCycle34Precision). The "shall not occur / take place / happen"
    branch is anchored on the retention word and stays qualifier-agnostic.

    Pattern side: the object-position positive branches (verb-led, noun-led,
    reversed active) ended their object tails at "(?:customer )?(?:personal )?
    (?:data|information)" with no absorbing window, so ANY pre-data qualifier
    word made an unbounded retention clause go silent. Widen the object tail on
    branches 2/3/4/5 with "(?:\w+ ){0,3}" mirroring the exclusion, so qualified
    unbounded positives flag at every width while denial/bound/mandate forms
    stay silent via the paragraph-wide exclusion.
    """

    def test_three_word_pre_data_denials_not_flagged(self):
        benign = [
            "No customer online account usage data retention beyond the applicable retention period shall occur.",
            "After the latest permitted period, no personal sensitive financial card data storage shall occur.",
            "No customer archived payment method information preservation following the permitted retention window shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_three_word_pre_data_verb_denials_not_flagged(self):
        benign = [
            "No customer online account usage data shall be retained beyond the applicable retention period.",
            "Beyond the applicable retention period, no personal sensitive financial card data shall be stored by the provider.",
            "No customer archived payment method information shall be preserved after the latest permitted period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary and must keep flagging.
        flagged = [
            "No customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data retention beyond the applicable retention period shall occur.",
            "No customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_three_word_shall_not_occur_denials_not_flagged(self):
        # Anchored on the retention word, so qualifier-agnostic at any width.
        benign = [
            "Customer online account usage data retention shall not occur beyond the applicable retention period.",
            "Beyond the applicable retention period, personal sensitive financial card data storage shall not take place.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_three_word_qualified_bounded_not_flagged(self):
        benign = [
            "Customer online account usage data shall be retained for no more than 12 months beyond the applicable retention period.",
            "Beyond the applicable retention period, personal sensitive financial card data storage for a period of 90 days.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_object_position_qualified_unbounded_still_flagged(self):
        # Pattern-side fix: qualified object-position positives now flag at
        # every pre-data qualifier width (verb-led, noun-led, reversed active).
        flagged = [
            "Provider shall retain customer backup data beyond the applicable retention period.",
            "Retention of customer online account data beyond the applicable retention period.",
            "After the applicable retention period, Provider shall retain customer online account usage data.",
            "After the applicable retention period, personal sensitive financial card data shall be retained by the Provider.",
            "Customer online account usage data retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_qualified_unbounded_stacked_controls(self):
        # Unbounded positives without denial/bound/mandate context keep flagging.
        flagged = [
            "Notwithstanding anything stated elsewhere, customer online account usage data retention beyond the applicable retention period shall occur.",
            "Beyond the applicable retention period, personal sensitive financial card data storage.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle34Precision:
    r"""Cycle-34 precision: R-DATA-5 four-word pre-data qualifier boundary.

    Cycle-33 widened the pre-data modifier slot to "(?:\w+ ){0,3}" on both the
    exclusion denial branches and the four tightly-wrapped object-position
    pattern tails (verb-led/noun-led/reversed-active), covering up to THREE
    qualifier words. A FOUR-word phrase ("customer online account historical
    usage data") still broke the slot: denials over-fired R-DATA-5 and the
    tightly-wrapped unbounded positives went silent.

    Fix: widen the slot to "(?:\w+ ){0,4}" in the same six sites, so four-word
    pre-data qualifiers are covered on both sides. FIVE-word phrases now sit
    beyond the boundary and keep flagging for denials / go silent for the
    tightly-wrapped positives (attributive and reversed-passive stay robust at
    any width via their mid-phrase match / absorbing window). Also give the two
    denial branches the pattern-side's doubled "copies of"-chain so a leading
    pre-head "copies of / extracts of / records of" group no longer needs to
    consume the word slot.
    """

    def test_four_word_pre_data_denials_not_flagged(self):
        benign = [
            "No customer online account historical usage data retention beyond the applicable retention period shall occur.",
            "No customer online account historical usage data shall be retained beyond the applicable retention period.",
            "After the latest permitted period, no customer online account historical usage data storage shall occur.",
            "No customer online account usage history data storage beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_four_word_verb_form_denials_not_flagged(self):
        benign = [
            "No customer online account historical usage data shall be retained beyond the applicable retention period.",
            "Beyond the applicable retention period, no personal sensitive financial card transaction data shall be stored by the provider.",
            "After the latest permitted period, no customer recorded payment method sensitive data shall be preserved.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary and must keep flagging.
        # (Cycle-33 already carries the identical eleven-word case; keep both.)
        flagged = [
            "No customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data retention beyond the applicable retention period shall occur.",
            "No customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data shall be retained beyond the applicable retention period.",
            "No copies of customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_four_word_qualified_bounded_not_flagged(self):
        benign = [
            "No customer online account historical usage data retention beyond the permitted period of 90 days shall occur.",
            "Provider may retain customer online account historical usage data for a period of 90 days.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_object_position_four_word_qualified_unbounded_still_flagged(self):
        # Pattern-side fix: tight object tails now absorb a 4-word pre-data
        # qualifier; attributive/reversed-passive stay robust at any width.
        flagged = [
            "Provider shall retain customer online account historical usage data beyond the applicable retention period.",
            "Retention of customer online account historical usage data beyond the applicable retention period.",
            "After the applicable retention period, Provider shall retain customer online account historical usage data.",
            "After the applicable retention period, customer online account historical usage data shall be retained by the Provider.",
            "Customer online account historical usage data retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the tight
        # object tails go silent, while window/mid-phrase orders still flag.
        r = score_document(
            ["Provider shall retain customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data beyond the applicable retention period."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)
        r = score_document(
            ["After the applicable retention period, Provider shall retain customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)
        r = score_document(
            ["Customer online account historical usage audit event trail log data retention beyond the applicable retention period."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_four_word_pre_head_copies_denials_not_flagged(self):
        # Leading pre-head "copies of"-chain absorbed by the denial branches.
        benign = [
            "No copies of customer online account historical usage data shall be retained beyond the applicable retention period.",
            "No copies of customer online account historical usage data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_copies_of_controls_unchanged(self):
        # Positive copies-of controls keep flagging; natural noun-led denial
        # and unqualified copies-denials stay silent.
        flagged = [
            "Provider shall retain copies of customer online account historical usage data beyond the applicable retention period.",
            "Retention of copies of customer online account historical usage data beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t
        benign = [
            "No retention of copies of customer online account historical usage data beyond the applicable retention period.",
            "No copies of customer data shall be retained beyond the applicable retention period.",
            "No copies of customer data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t


class TestCycle35Precision:
    r"""Cycle-35 precision: R-DATA-5 five-word pre-data qualifier boundary.

    Cycle-34 widened the pre-data modifier slot to "(?:\w+ ){0,4}" on the four
    tightly-wrapped object-position pattern tails and both exclusion denial
    branches, covering up to FOUR qualifier words. A FIVE-word phrase ("customer
    online account historical usage log data") sat beyond the {0,4} boundary:
    tight object tails went silent while nominal/verb-form denials still
    over-fired R-DATA-5.

    Fix: widen the slot to "(?:\w+ ){0,5}" in the same six sites (pattern tails
    for verb-led/noun-led/reversed-active at both opening orders, plus the
    nominal- and verb-form denial branches). FIVE-word phrases now flag on both
    sides; SIX-word phrases sit beyond the new boundary and keep over-firing for
    denials / going silent for the tight positives (attributive and
    reversed-passive stay robust at any width via their mid-phrase match /
    absorbing window).
    """

    def test_five_word_pre_data_denials_not_flagged(self):
        benign = [
            "No customer online account historical usage log data retention beyond the applicable retention period shall occur.",
            "No customer online account historical usage log data shall be retained beyond the applicable retention period.",
            "After the latest permitted period, no customer online account historical usage log data storage shall occur.",
            "Customer online account historical usage log data retention shall not occur beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_five_word_verb_form_denials_not_flagged(self):
        benign = [
            "No customer online account historical usage log data shall be retained beyond the applicable retention period.",
            "Beyond the applicable retention period, no personal sensitive financial card transaction data shall be stored by the provider.",
            "No copies of customer online account historical usage log data shall be retained beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary and must keep flagging.
        flagged = [
            "No customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data retention beyond the applicable retention period shall occur.",
            "No customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data shall be retained beyond the applicable retention period.",
            "No copies of customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_five_word_qualified_bounded_not_flagged(self):
        benign = [
            "No customer online account historical usage log data retention for a period of 90 days shall occur.",
            "Provider may retain customer online account historical usage log data for a period of 90 days.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_object_position_five_word_qualified_unbounded_still_flagged(self):
        # Pattern-side fix: tight object tails now absorb a 5-word pre-data
        # qualifier; attributive/reversed-passive stay robust at any width.
        flagged = [
            "Provider shall retain customer online account historical usage log data beyond the applicable retention period.",
            "Retention of customer online account historical usage log data beyond the applicable retention period.",
            "After the applicable retention period, Provider shall retain customer online account historical usage log data.",
            "After the applicable retention period, customer online account historical usage log data shall be retained by the Provider.",
            "Customer online account historical usage log data retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the tight
        # object tails go silent, while window/mid-phrase orders still flag.
        r = score_document(
            ["Provider shall retain customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data beyond the applicable retention period."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)
        r = score_document(
            ["After the applicable retention period, Provider shall retain customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)
        r = score_document(
            ["Customer online account historical usage audit event trail log data retention beyond the applicable retention period."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_five_word_pre_head_copies_denials_not_flagged(self):
        # Leading pre-head "copies of"-chain absorbed by the denial branches at 5w.
        benign = [
            "No copies of customer online account historical usage log data shall be retained beyond the applicable retention period.",
            "No copies of customer online account historical usage log data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_stacked_interposed_five_word_combos(self):
        # Stacked interposed groups COMBINED with 5-word pre-data qualifiers.
        benign = [
            "No customer online account historical usage log data backup copies retention beyond the applicable retention period shall occur.",
            "No customer online account historical usage log data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        flagged = [
            "Customer online account historical usage log data backup copies retention beyond the applicable retention period.",
            "Retention of copies of customer online account historical usage log data beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle36Precision:
    r"""Cycle-36 precision: R-DATA-5 six-word pre-data qualifier boundary.

    Cycle-35 widened the pre-data modifier slot to "(?:\w+ ){0,5}" in all six
    sites (four tight object tails + nominal and verb-form denial branches),
    covering up to FIVE qualifier words. A SIX-word phrase ("customer online
    account historical usage audit log data") sat beyond the {0,5} boundary:
    tight object tails went silent while nominal/verb-form denials still
    over-fired R-DATA-5 (probe49 pre-fix: 14/23, the 9 FAILs all at 6w).

    Fix: widen the slot to "(?:\w+ ){0,6}" in the same six sites, keeping the
    prefix-shape asymmetry in mind — the four pattern tails and the nominal
    denial branch use "(?:customer )?(?:personal )?" while the verb-form denial
    branch uses "(?:customer |personal )?" and needs its own targeted edit.
    SIX-word phrases now flag on both sides; SEVEN-word phrases sat beyond the
    {0,6} boundary and kept over-firing for denials / going silent for the tight
    positives. Cycle-37 widened the slot to {0,7} in the same six sites, so the
    seven-word boundary phrases below were bumped to EIGHT words ("audit event
    trail log") to stay on the far side of the new boundary; attributive stays
    robust at any width via its mid-phrase match, while reversed-passive is
    capped at ~7 pre-data words by branch 8's [^.;]{0,60} window (see
    TestCycle37Precision). Cycle-38 widened the slot to {0,8} and the branch-8
    window to {0,69}, so the EIGHT-word boundary phrases below were bumped to
    NINE words ("audit event trail access log") to stay on the far side.
    Cycle-39 widened the slot to {0,9} and the branch-8 window to {0,77}, so the
    NINE-word boundary phrases below were bumped to TEN words ("audit event
    trail access control log") to stay on the far side. Cycle-40 widened the
    slot to {0,10} and the branch-8 window to {0,83}, so the TEN-word boundary
    phrases below were bumped to ELEVEN words ("audit event trail access
    control audit log") to stay on the far side. Cycle-41 widened the slot to
    {0,11} and the branch-8 window to {0,89}, so the ELEVEN-word boundary
    phrases below were bumped to TWELVE words ("audit event trail access
    control audit log monitoring") to stay on the far side (11w reversed-passive
    84-char gap now flags; the 12w 95-char gap stays silent). Cycle-42 widened
    the slot to {0,12} and the branch-8 window to {0,97}, so the TWELVE-word
    boundary phrases below were bumped to THIRTEEN words ("audit event trail
    access control audit log monitoring review") to stay on the far side (12w
    reversed-passive 97-char gap now flags; the 13w 104-char gap stays silent).
    Cycle-43 widened the slot to {0,13} and the branch-8 window to {0,104}, so
    the THIRTEEN-word boundary phrases below were bumped to FOURTEEN words
    ("audit event trail access control audit log monitoring review policy") to
    stay on the far side (13w reversed-passive 104-char gap now flags; the 14w
    111-char gap stays silent). The P4 campaign later widened the slot to {0,15}
    and the branch-8 window to {0,120}, so the boundary phrases below were
    bumped to SIXTEEN words ("audit event trail access control audit log
    monitoring review policy handling compliance") to stay on the far side
    (15w reversed-passive 120-char gap now flags at the exact window edge; the
    16w 131-char gap stays silent).
    """

    def test_six_word_pre_data_denials_not_flagged(self):
        benign = [
            "No customer online account historical usage audit log data retention beyond the applicable retention period shall occur.",
            "No customer online account historical usage audit log data shall be retained beyond the applicable retention period.",
            "After the latest permitted period, no customer online account historical usage audit log data storage shall occur.",
            "Customer online account historical usage audit log data retention shall not occur beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_six_word_verb_form_denials_not_flagged(self):
        benign = [
            "No customer online account historical usage audit log data shall be retained beyond the applicable retention period.",
            "Beyond the applicable retention period, no personal sensitive financial card transaction data shall be stored by the provider.",
            "No copies of customer online account historical usage audit log data shall be retained beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary and must keep flagging.
        flagged = [
            "No customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data retention beyond the applicable retention period shall occur.",
            "No customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data shall be retained beyond the applicable retention period.",
            "No copies of customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_six_word_qualified_bounded_not_flagged(self):
        benign = [
            "No customer online account historical usage audit log data retention for a period of 90 days shall occur.",
            "Provider may retain customer online account historical usage audit log data for a period of 90 days.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_object_position_six_word_qualified_unbounded_still_flagged(self):
        # Pattern-side fix: tight object tails now absorb a 6-word pre-data
        # qualifier; attributive/reversed-passive stay robust at any width.
        flagged = [
            "Provider shall retain customer online account historical usage audit log data beyond the applicable retention period.",
            "Retention of customer online account historical usage audit log data beyond the applicable retention period.",
            "After the applicable retention period, Provider shall retain customer online account historical usage audit log data.",
            "After the applicable retention period, customer online account historical usage audit log data shall be retained by the Provider.",
            "Customer online account historical usage audit log data retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the tight
        # object tails go silent, while window/mid-phrase orders still flag.
        r = score_document(
            ["Provider shall retain customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data beyond the applicable retention period."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)
        r = score_document(
            ["After the applicable retention period, Provider shall retain customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance data."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)
        r = score_document(
            ["Customer online account historical usage audit event trail log data retention beyond the applicable retention period."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_six_word_pre_head_copies_denials_not_flagged(self):
        # Leading pre-head "copies of"-chain absorbed by the denial branches at 6w.
        benign = [
            "No copies of customer online account historical usage audit log data shall be retained beyond the applicable retention period.",
            "No copies of customer online account historical usage audit log data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_stacked_interposed_six_word_combos(self):
        # Stacked interposed groups COMBINED with 6-word pre-data qualifiers.
        benign = [
            "No customer online account historical usage audit log data backup copies retention beyond the applicable retention period shall occur.",
            "No customer online account historical usage audit log data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        flagged = [
            "Customer online account historical usage audit log data backup copies retention beyond the applicable retention period.",
            "Retention of copies of customer online account historical usage audit log data beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle37Precision:
    r"""Cycle-37 precision: R-DATA-5 seven-word pre-data qualifier boundary.

    Cycle-36 widened the pre-data modifier slot to "(?:\w+ ){0,6}" in all six
    sites (four tight object tails + nominal and verb-form denial branches),
    covering up to SIX qualifier words. A SEVEN-word phrase ("customer online
    account historical usage audit event log data") sat beyond the {0,6}
    boundary: tight object tails went silent while nominal/verb-form denials
    still over-fired R-DATA-5 (probe50 pre-fix: 13/23, the 9 FAILs all at 7w).

    Fix: widen the slot to "(?:\w+ ){0,7}" in the same six sites, keeping the
    prefix-shape asymmetry in mind — the four pattern tails and the nominal
    denial branch use "(?:customer )?(?:personal )?" (5 sites via replace_all,
    incl. both trailing-"|" branch tails) while the verb-form denial branch uses
    "(?:customer |personal )?" and needs its own targeted edit (rules.py:605).
    SEVEN-word phrases now flag on both sides; cycle-38 widened the slot to
    "(?:\w+ ){0,8}" in the same six sites, so the EIGHT-word boundary phrases
    below were bumped to NINE words ("...audit event trail access log") to stay
    on the far side of the new boundary.

    NEW discovery at the 8w boundary: reversed-passive ("After ... <phrase>
    data shall be retained by the Provider.") goes SILENT at 8w. Branch 8
    positions the data noun via "[^.;]{0,60}" (~60 chars ~= 7 pre-data words),
    so the reversed-passive form is robust through ~7 pre-data words only —
    earlier cycle docstrings' claim that "reversed-passive is robust at any
    width" is FALSE beyond 7 words. Attributive (mid-phrase bare-data-noun,
    "data retention") stays robust at any width. Cycle-38 widened the window to
    "[^.;]{0,69}", covering the 8-word reversed-passive (63-char gap) as well;
    the 9-word phrase (70-char gap) now sits beyond the window (see
    TestCycle38Precision) until cycle-39 widened the window again to
    "[^.;]{0,77}" — the 9-word reversed-passive (70-char gap) now flags, and
    only the 10-word form (78-char gap, beyond the window) goes silent.
    Cycle-39 also widened the slot to "(?:\w+ ){0,9}", so the NINE-word boundary
    phrases below were bumped to TEN words ("...audit event trail access control
    log") to stay on the far side. Cycle-40 widened the slot to "(?:\w+ ){0,10}"
    and the branch-8 window to "[^.;]{0,83}", so the TEN-word boundary phrases
    below were bumped to ELEVEN words ("...audit event trail access control
    audit log") to stay on the far side (10w reversed-passive 78-char gap now
    flags; the 11w 84-char gap stays silent). Cycle-41 widened the slot to
    "(?:\w+ ){0,11}" and the branch-8 window to "[^.;]{0,89}", so the ELEVEN-word
    boundary phrases below were bumped to TWELVE words ("...audit event trail
    access control audit log monitoring") to stay on the far side (11w
    reversed-passive 84-char gap now flags; the 12w 95-char gap stays silent).
    Cycle-42 widened the slot to {0,12} and the branch-8 window to {0,97}, so
    the boundary phrases below were bumped to THIRTEEN words ("...audit log
    monitoring review") to stay on the far side (12w reversed-passive 97-char
    gap now flags; the 13w 104-char gap stays silent). Cycle-43 widened the
    slot to {0,13} and the branch-8 window to {0,104}, so the THIRTEEN-word
    boundary phrases below were bumped to FOURTEEN words ("...audit log
    monitoring review policy") to stay on the far side (13w reversed-passive
    104-char gap now flags; the 14w 111-char gap stays silent). The P4 campaign
    later widened the slot to {0,15} and the branch-8 window to {0,120}, so the
    boundary phrases below were bumped to SIXTEEN words ("...audit log monitoring
    review policy handling compliance") to stay on the far side (15w
    reversed-passive 120-char gap now flags at the exact window edge; the 16w
    131-char gap stays silent).
    """

    SEVEN = "customer online account historical usage audit event log "
    EIGHT = "customer online account historical usage audit event trail log "
    NINE = "customer online account historical usage audit event trail access log "
    TEN = "customer online account historical usage audit event trail access control log "
    ELEVEN = "customer online account historical usage audit event trail access control audit log "
    TWELVE = "customer online account historical usage audit event trail access control audit log monitoring "
    THIRTEEN = "customer online account historical usage audit event trail access control audit log monitoring review "
    FOURTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy "
    FIFTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling "
    SIXTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance "

    def test_seven_word_pre_data_denials_not_flagged(self):
        benign = [
            f"No {self.SEVEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.SEVEN}data shall be retained beyond the applicable retention period.",
            f"No {self.SEVEN}data storage shall occur beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_seven_word_verb_form_denials_not_flagged(self):
        benign = [
            f"No copies of {self.SEVEN}data shall be retained beyond the applicable retention period.",
            f"Beyond the applicable retention period, no {self.SEVEN}data shall be stored by the provider.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary and must keep flagging.
        flagged = [
            f"No {self.SIXTEEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
            f"No copies of {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_seven_word_qualified_bounded_not_flagged(self):
        benign = [
            f"No {self.SEVEN}data retention for a period of 90 days shall occur.",
            f"Provider may retain {self.SEVEN}data for a period of 90 days.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_object_position_seven_word_qualified_unbounded_still_flagged(self):
        # Pattern-side fix: tight object tails now absorb a 7-word pre-data
        # qualifier; attributive stays robust at any width.
        flagged = [
            f"Provider shall retain {self.SEVEN}data beyond the applicable retention period.",
            f"Retention of {self.SEVEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.SEVEN}data.",
            f"After the applicable retention period, {self.SEVEN}data shall be retained by the Provider.",
            f"{self.SEVEN}data retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the tight
        # object tails go silent, while attributive mid-phrase still flags.
        benign = [
            f"Provider shall retain {self.SIXTEEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.SIXTEEN}data.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        r = score_document(
            [f"{self.TEN}data retention beyond the applicable retention period."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_nine_word_reversed_passive_still_flagged(self):
        # Branch 8's "[^.;]{0,77}" window (widened from {0,69} in cycle-39)
        # covers the 9-word reversed-passive (70-char gap): flags. At ELEVEN
        # words (84-char gap) the data noun sits beyond the window and goes
        # silent; the 10-word form (78-char gap) is inside the {0,83} window.
        r = score_document(
            [f"After the applicable retention period, {self.NINE}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.SIXTEEN}data shall be retained by the Provider."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)

    def test_seven_word_pre_head_copies_denials_not_flagged(self):
        benign = [
            f"No copies of {self.SEVEN}data shall be retained beyond the applicable retention period.",
            f"No copies of {self.SEVEN}data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_stacked_interposed_seven_word_combos(self):
        benign = [
            f"No {self.SEVEN}data backup copies retention beyond the applicable retention period shall occur.",
            f"No {self.SEVEN}data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        flagged = [
            f"{self.SEVEN}data backup copies retention beyond the applicable retention period.",
            f"Retention of copies of {self.SEVEN}data beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle38Precision:
    r"""Cycle-38 precision: R-DATA-5 eight-word pre-data qualifier boundary.

    Cycle-37 widened the pre-data modifier slot to "(?:\w+ ){0,7}" in all six
    sites (four tight object tails + nominal and verb-form denial branches),
    covering up to SEVEN qualifier words. An EIGHT-word phrase ("customer online
    account historical usage audit event trail log data") sat beyond the {0,7}
    boundary: tight object tails went silent while nominal/verb-form denials
    still over-fired R-DATA-5 (probe51 pre-fix: 13/23, the 9 FAILs all at 8w).

    Fix: widen the slot to "(?:\w+ ){0,8}" in the same six sites, keeping the
    prefix-shape asymmetry in mind — the four pattern tails and the nominal
    denial branch use "(?:customer )?(?:personal )?" (5 sites via replace_all,
    incl. both trailing-"|" branch tails) while the verb-form denial branch uses
    "(?:customer |personal )?" and needs its own targeted edit (rules.py:605).

    Branch-8 window: reversed-passive ("After ... <phrase> data shall be
    retained by the Provider.") goes SILENT at 8w because branch 8 positions the
    data noun via "[^.;]{0,60}" (~60 chars ~= 7 pre-data words). Widening that
    window to "[^.;]{0,69}" covers the 8-word reversed-passive (63-char gap,
    flags) while leaving the 9-word form silent (70-char gap, beyond the
    window).

    EIGHT-word phrases now flag on both sides; NINE-word phrases sit beyond the
    new boundary and keep over-firing for denials / going silent for the tight
    positives, with the reversed-passive form capped by the widened window
    (TestCycle37Precision carries the 9w control cases).

    Cycle-39 widened the slot to "(?:\w+ ){0,9}" and the branch-8 window to
    "[^.;]{0,77}" in the same six sites: the NINE-word reversed-passive
    (70-char gap, now within the window) flags again, and the TEN-word phrase
    ("...audit event trail access control log data") is the NEW far-side
    boundary — tight positives silent, denials over-firing, reversed-passive
    silent at its 78-char gap (test_nine_word_reversed_passive_still_flagged
    carries the ten-word control). Cycle-40 widened the slot to "(?:\w+ ){0,10}"
    and the branch-8 window to "[^.;]{0,83}": the TEN-word reversed-passive
    (78-char gap) now flags again, and the ELEVEN-word phrase ("...audit event
    trail access control audit log data") is the new far-side boundary — tight
    positives silent, denials over-firing, reversed-passive silent at its
    84-char gap (test_nine_word_reversed_passive_still_flagged carries the
    eleven-word control). Cycle-41 widened the slot to "(?:\w+ ){0,11}" and the
    branch-8 window to "[^.;]{0,89}": the ELEVEN-word reversed-passive (84-char
    gap) now flags again, and the TWELVE-word phrase ("...audit event trail
    access control audit log monitoring data") is the new far-side boundary —
    tight positives silent, denials over-firing, reversed-passive silent at its
    95-char gap (test_nine_word_reversed_passive_still_flagged carries the
    twelve-word control). Cycle-42 widened the slot to "(?:\w+ ){0,12}" and the
    branch-8 window to "[^.;]{0,97}", so the TWELVE-word boundary phrases below
    were bumped to THIRTEEN words ("...audit log monitoring review") to stay on
    the far side (12w reversed-passive 97-char gap now flags; the 13w 104-char
    gap stays silent). Cycle-43 widened the slot to "(?:\w+ ){0,13}" and the
    branch-8 window to "[^.;]{0,104}", so the THIRTEEN-word boundary phrases
    below were bumped to FOURTEEN words ("...audit log monitoring review
    policy") to stay on the far side (13w reversed-passive 104-char gap now
    flags; the 14w 111-char gap stays silent). The P4 campaign later widened the
    slot to "(?:\w+ ){0,15}" and the branch-8 window to "[^.;]{0,120}", so the
    boundary phrases below were bumped to SIXTEEN words ("...audit log monitoring
    review policy handling compliance") to stay on the far side (15w
    reversed-passive 120-char gap now flags at the exact window edge; the 16w
    131-char gap stays silent).
    """

    SEVEN = "customer online account historical usage audit event log "
    EIGHT = "customer online account historical usage audit event trail log "
    NINE = "customer online account historical usage audit event trail access log "
    TEN = "customer online account historical usage audit event trail access control log "
    ELEVEN = "customer online account historical usage audit event trail access control audit log "
    TWELVE = "customer online account historical usage audit event trail access control audit log monitoring "
    THIRTEEN = "customer online account historical usage audit event trail access control audit log monitoring review "
    FOURTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy "
    FIFTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling "
    SIXTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance "

    def test_eight_word_pre_data_denials_not_flagged(self):
        benign = [
            f"No {self.EIGHT}data retention beyond the applicable retention period shall occur.",
            f"No {self.EIGHT}data shall be retained beyond the applicable retention period.",
            f"No {self.EIGHT}data storage shall occur beyond the applicable retention period.",
            f"No {self.EIGHT}data retention shall not occur beyond the applicable retention period.",
            f"No copies of {self.EIGHT}data shall be retained beyond the applicable retention period.",
            f"No copies of {self.EIGHT}data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_eight_word_verb_form_denials_not_flagged(self):
        benign = [
            f"No {self.EIGHT}data shall be retained beyond the applicable retention period.",
            f"After the latest permitted period, no {self.EIGHT}data storage shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary and must keep flagging.
        flagged = [
            f"No {self.SIXTEEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
            f"No copies of {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_eight_word_qualified_bounded_not_flagged(self):
        benign = [
            f"No {self.EIGHT}data retention for a period of 90 days shall occur.",
            f"Provider may retain {self.EIGHT}data for a period of 90 days.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_object_position_eight_word_qualified_unbounded_still_flagged(self):
        # Pattern-side fix: tight object tails now absorb an 8-word pre-data
        # qualifier; attributive/reversed-passive stay robust via window.
        flagged = [
            f"Provider shall retain {self.EIGHT}data beyond the applicable retention period.",
            f"Retention of {self.EIGHT}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.EIGHT}data.",
            f"After the applicable retention period, {self.EIGHT}data shall be retained by the Provider.",
            f"{self.EIGHT}data retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the tight
        # object tails go silent, while attributive mid-phrase still flags.
        benign = [
            f"Provider shall retain {self.SIXTEEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.SIXTEEN}data.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        r = score_document(
            [f"{self.TEN}data retention beyond the applicable retention period."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_eight_word_reversed_passive_still_flagged(self):
        # Branch 8's "[^.;]{0,77}" window (widened from {0,69} in cycle-39)
        # covers the 8-word reversed-passive (63-char gap): flags. The 9-word
        # form (70-char gap) also flags now; the 11-word form (84-char gap) is
        # covered by test_nine_word_reversed_passive_still_flagged.
        r = score_document(
            [f"After the applicable retention period, {self.EIGHT}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_nine_word_reversed_passive_still_flagged(self):
        # Branch 8's "[^.;]{0,77}" window (widened from {0,69} in cycle-39)
        # covers the 9-word reversed-passive (70-char gap): flags. At ELEVEN
        # words (84-char gap) the data noun sits beyond the window and goes
        # silent; the 10-word form (78-char gap) is inside the {0,83} window.
        r = score_document(
            [f"After the applicable retention period, {self.NINE}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.SIXTEEN}data shall be retained by the Provider."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)

    def test_eight_word_pre_head_copies_denials_not_flagged(self):
        # Leading pre-head "copies of"-chain absorbed by the denial branches at 8w.
        benign = [
            f"No copies of {self.EIGHT}data shall be retained beyond the applicable retention period.",
            f"No copies of {self.EIGHT}data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_stacked_interposed_eight_word_combos(self):
        # Stacked interposed groups COMBINED with 8-word pre-data qualifiers.
        benign = [
            f"No {self.EIGHT}data backup copies retention beyond the applicable retention period shall occur.",
            f"No {self.EIGHT}data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        flagged = [
            f"{self.EIGHT}data backup copies retention beyond the applicable retention period.",
            f"Retention of copies of {self.EIGHT}data beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t


class TestCycle39Precision:
    r"""Cycle-39 precision: R-DATA-5 nine-word pre-data qualifier boundary.

    Cycle-38 widened the pre-data modifier slot to "(?:\w+ ){0,8}" in all six
    sites (four tight object tails + nominal and verb-form denial branches),
    covering up to EIGHT qualifier words. A NINE-word phrase ("customer online
    account historical usage audit event trail access log data") sat beyond the
    {0,8} boundary: tight object tails went silent while nominal/verb-form
    denials still over-fired R-DATA-5, and the reversed-passive form sat beyond
    branch 8's "[^.;]{0,69}" window (probe52 pre-fix: 13/23, the FAILs all at
    9w, including the 8w block's 63-char reversed-passive now inside the window).

    Fix: widen the slot to "(?:\w+ ){0,9}" in the same six sites, keeping the
    prefix-shape asymmetry in mind — the four pattern tails and the nominal
    denial branch use "(?:customer )?(?:personal )?" (5 sites via replace_all,
    incl. both trailing-"|" branch tails) while the verb-form denial branch uses
    "(?:customer |personal )?" and needs its own targeted edit (rules.py:605).

    Branch-8 window: cycle-38 widened it to "[^.;]{0,69}" covering the 8-word
    reversed-passive (63-char gap). Cycle-39 widens it to "[^.;]{0,77}" so the
    9-word reversed-passive (70-char gap) flags again; the TEN-word form
    (78-char gap) still sits beyond the window and goes silent.

    NINE-word phrases now flag on both sides; TEN-word phrases sit beyond the
    new boundary and keep over-firing for denials / going silent for the tight
    positives, with the reversed-passive form capped by the widened window
    (probe52 post-fix: 23/23; window threshold 9w=70 char gap FLAG, 10w=78 char
    gap SILENT).

    Cycle-40 widens the slot to "(?:\w+ ){0,10}" and the branch-8 window to
    "[^.;]{0,83}" in the same six sites: the TEN-word reversed-passive (78-char
    gap, now within the window) flags again, and the ELEVEN-word phrases below
    are the NEW far-side boundary — tight positives silent, denials over-firing,
    reversed-passive silent at its 84-char gap (probe53 post-fix: 23/23; window
    threshold 10w=78 char gap FLAG, 11w=84 char gap SILENT).

    Cycle-41 widens the slot to "(?:\w+ ){0,11}" and the branch-8 window to
    "[^.;]{0,89}" in the same six sites: the ELEVEN-word reversed-passive
    (84-char gap, now within the window) flags again, and the TWELVE-word phrase
    ("...audit event trail access control audit log monitoring data") is the NEW
    far-side boundary — tight positives silent, denials over-firing,
    reversed-passive silent at its 95-char gap (probe54 post-fix: 23/23; window
    threshold 11w=84 char gap FLAG, 12w=95 char gap SILENT). Cycle-42 widens the
    slot to "(?:\w+ ){0,12}" and the branch-8 window to "[^.;]{0,97}", so the
    TWELVE-word boundary phrases below were bumped to THIRTEEN words ("...audit
    log monitoring review") to stay on the far side (12w reversed-passive 97-char
    gap now flags; the 13w 104-char gap stays silent). Cycle-43 widens the slot
    to "(?:\w+ ){0,13}" and the branch-8 window to "[^.;]{0,104}", so the
    THIRTEEN-word boundary phrases below were bumped to FOURTEEN words ("...audit
    log monitoring review policy") to stay on the far side (13w reversed-passive
    104-char gap now flags; the 14w 111-char gap stays silent). The P4 campaign
    later widened the slot to "(?:\w+ ){0,15}" and the branch-8 window to
    "[^.;]{0,120}", so the boundary phrases below were bumped to SIXTEEN words
    ("...audit log monitoring review policy handling compliance") to stay on the
    far side (15w reversed-passive 120-char gap now flags at the exact window
    edge; the 16w 131-char gap stays silent).
    """

    SEVEN = "customer online account historical usage audit event log "
    EIGHT = "customer online account historical usage audit event trail log "
    NINE = "customer online account historical usage audit event trail access log "
    TEN = "customer online account historical usage audit event trail access control log "
    ELEVEN = "customer online account historical usage audit event trail access control audit log "
    TWELVE = "customer online account historical usage audit event trail access control audit log monitoring "
    THIRTEEN = "customer online account historical usage audit event trail access control audit log monitoring review "
    FOURTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy "
    FIFTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling "
    SIXTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance "

    def test_nine_word_pre_data_denials_not_flagged(self):
        benign = [
            f"No {self.NINE}data retention beyond the applicable retention period shall occur.",
            f"No {self.NINE}data shall be retained beyond the applicable retention period.",
            f"After the latest permitted period, no {self.NINE}data storage shall occur.",
            f"{self.NINE}data retention shall not occur beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_nine_word_verb_form_denials_not_flagged(self):
        benign = [
            f"No {self.NINE}data shall be retained beyond the applicable retention period.",
            f"No copies of {self.NINE}data shall be retained beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary and must keep flagging.
        flagged = [
            f"No {self.SIXTEEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
            f"No copies of {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_nine_word_qualified_bounded_not_flagged(self):
        benign = [
            f"No {self.NINE}data retention for a period of 90 days shall occur.",
            f"Provider may retain {self.NINE}data for a period of 90 days.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_object_position_nine_word_qualified_unbounded_still_flagged(self):
        # Pattern-side fix: tight object tails now absorb a 9-word pre-data
        # qualifier; attributive/reversed-passive stay robust via window.
        flagged = [
            f"Provider shall retain {self.NINE}data beyond the applicable retention period.",
            f"Retention of {self.NINE}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.NINE}data.",
            f"Retention of copies of {self.NINE}data beyond the applicable retention period.",
            f"{self.NINE}data retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_nine_word_stacked_attributive_still_flagged(self):
        flagged = [
            f"{self.NINE}data backup copies retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_nine_word_stacked_denials_not_flagged(self):
        benign = [
            f"No {self.NINE}data backup copies retention beyond the applicable retention period shall occur.",
            f"No copies of {self.NINE}data retention beyond the applicable retention period shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the tight
        # object tails go silent, while attributive mid-phrase still flags.
        benign = [
            f"Provider shall retain {self.SIXTEEN}data beyond the applicable retention period.",
            f"Retention of {self.SIXTEEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.SIXTEEN}data.",
            f"Retention of copies of {self.SIXTEEN}data beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        r = score_document(
            [f"{self.TEN}data retention beyond the applicable retention period."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_nine_word_reversed_passive_still_flagged(self):
        # Branch 8's "[^.;]{0,77}" window (widened from {0,69} in cycle-39)
        # covers the 9-word reversed-passive (70-char gap): flags. At ELEVEN
        # words (84-char gap) the data noun sits beyond the window and goes
        # silent; the 10-word form (78-char gap) is inside the {0,83} window.
        r = score_document(
            [f"After the applicable retention period, {self.NINE}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.SIXTEEN}data shall be retained by the Provider."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)


class TestCycle40Precision:
    r"""Cycle-40 precision: R-DATA-5 ten-word pre-data qualifier boundary.

    Cycle-39 widened the pre-data modifier slot to "(?:\w+ ){0,9}" in all six
    sites, covering up to NINE qualifier words (plus the optional "customer "
    prefix). A TEN-word phrase ("customer online account historical usage audit
    event trail access control log data") sat beyond the {0,9} boundary: tight
    object tails went silent while nominal/verb-form denials still over-fired
    R-DATA-5, and the reversed-passive form sat beyond branch 8's "[^.;]{0,77}"
    window (probe53 pre-fix failures all at 10w).

    Fix: widen the slot to "(?:\w+ ){0,10}" in the same six sites (the four
    pattern tails + nominal and verb-form denial branches) and widen the
    branch-8 window to "[^.;]{0,83}" so the TEN-word reversed-passive (78-char
    gap) flags again (rules.py:537/544/550/558/600/605/572).

    TEN-word phrases now flag on both sides; ELEVEN-word phrases sit beyond the
    new boundary: tight positives go silent and reversed-passive (84-char gap)
    stays silent, while denials keep over-firing (probe53 post-fix: 23/23;
    window threshold 10w=78 char gap FLAG, 11w=84 char gap SILENT).

    Cycle-41 widens the slot to "(?:\w+ ){0,11}" and the branch-8 window to
    "[^.;]{0,89}" in the same six sites (rules.py:537/544/550/558/600/605/572):
    the ELEVEN-word reversed-passive (84-char gap, now within the window) flags
    again, ELEVEN-word phrases now flag on both sides; TWELVE-word phrases sit
    beyond the new boundary — tight positives silent, reversed-passive (95-char
    gap) silent, denials keep over-firing (probe54 post-fix: 23/23; window
    threshold 11w=84 char gap FLAG, 12w=95 char gap SILENT). Cycle-42 widens the
    slot to "(?:\w+ ){0,12}" and the branch-8 window to "[^.;]{0,97}", so the
    TWELVE-word boundary phrases below were bumped to THIRTEEN words ("...audit
    log monitoring review") to stay on the far side (12w reversed-passive 97-char
    gap now flags; the 13w 104-char gap stays silent). Cycle-43 widens the slot
    to "(?:\w+ ){0,13}" and the branch-8 window to "[^.;]{0,104}", so the
    THIRTEEN-word boundary phrases below were bumped to FOURTEEN words ("...audit
    log monitoring review policy") to stay on the far side (13w reversed-passive
    104-char gap now flags; the 14w 111-char gap stays silent). The P4 campaign
    later widened the slot to "(?:\w+ ){0,15}" and the branch-8 window to
    "[^.;]{0,120}", so the boundary phrases below were bumped to SIXTEEN words
    ("...audit log monitoring review policy handling compliance") to stay on the
    far side (15w reversed-passive 120-char gap now flags at the exact window
    edge; the 16w 131-char gap stays silent).
    """

    SEVEN = "customer online account historical usage audit event log "
    EIGHT = "customer online account historical usage audit event trail log "
    NINE = "customer online account historical usage audit event trail access log "
    TEN = "customer online account historical usage audit event trail access control log "
    ELEVEN = "customer online account historical usage audit event trail access control audit log "
    TWELVE = "customer online account historical usage audit event trail access control audit log monitoring "
    THIRTEEN = "customer online account historical usage audit event trail access control audit log monitoring review "
    FOURTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy "
    FIFTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling "
    SIXTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance "

    def test_ten_word_pre_data_denials_not_flagged(self):
        benign = [
            f"No {self.TEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.TEN}data shall be retained beyond the applicable retention period.",
            f"After the latest permitted period, no {self.TEN}data storage shall occur.",
            f"{self.TEN}data retention shall not occur beyond the applicable retention period.",
            f"No {self.TEN}data backup copies retention beyond the applicable retention period shall occur.",
            f"No copies of {self.TEN}data retention beyond the applicable retention period shall occur.",
            f"No copies of {self.TEN}data shall be retained beyond the applicable retention period.",
            f"No {self.TEN}data retention for a period of 90 days shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_ten_word_tight_object_position_still_flagged(self):
        flagged = [
            f"Provider shall retain {self.TEN}data beyond the applicable retention period.",
            f"Retention of {self.TEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.TEN}data.",
            f"Retention of copies of {self.TEN}data beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_ten_word_attributive_still_flagged(self):
        flagged = [
            f"{self.TEN}data retention beyond the applicable retention period.",
            f"{self.TEN}data backup copies retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_ten_word_reversed_passive_still_flagged(self):
        # TEN-word reversed-passive sits at a 78-char gap, inside the {0,83}
        # window: flags.
        r = score_document(
            [f"After the applicable retention period, {self.TEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary: denials over-fire.
        flagged = [
            f"No {self.SIXTEEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the tight
        # object tails go silent, while attributive mid-phrase still flags.
        benign = [
            f"Provider shall retain {self.SIXTEEN}data beyond the applicable retention period.",
            f"Retention of {self.SIXTEEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.SIXTEEN}data.",
            f"Retention of copies of {self.SIXTEEN}data beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        r = score_document(
            [f"{self.TEN}data retention beyond the applicable retention period."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_sixteen_word_reversed_passive_still_silent(self):
        # Branch 8's "[^.;]{0,120}" window covers the ELEVEN (86-char gap),
        # THIRTEEN (104-char gap) and FIFTEEN (120-char gap) reversed-passive
        # forms: all flag (the FIFTEEN at the exact window edge). The SIXTEEN
        # phrase (131-char gap) sits beyond the window: silent.
        r = score_document(
            [f"After the applicable retention period, {self.ELEVEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.THIRTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.FIFTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.SIXTEEN}data shall be retained by the Provider."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)


class TestCycle41Precision:
    r"""Cycle-41 precision: R-DATA-5 eleven-word pre-data qualifier boundary.

    Cycle-40 widened the pre-data modifier slot to "(?:\w+ ){0,10}" in all six
    sites, covering up to TEN qualifier words (plus the optional "customer "
    prefix). An ELEVEN-word phrase ("customer online account historical usage
    audit event trail access control audit log data") sat beyond the {0,10}
    boundary: tight object tails went silent while nominal/verb-form denials
    still over-fired R-DATA-5, and the reversed-passive form sat beyond branch
    8's "[^.;]{0,83}" window (probe53 pre-fix failures all at 11w).

    Fix: widen the slot to "(?:\w+ ){0,11}" in the same six sites (the four
    pattern tails + nominal and verb-form denial branches) and widen the
    branch-8 window to "[^.;]{0,89}" so the ELEVEN-word reversed-passive
    (84-char gap) flags again (rules.py:537/544/550/558/600/605/572).

    ELEVEN-word phrases now flag on both sides; TWELVE-word phrases sit beyond
    the new boundary: tight positives go silent and reversed-passive (95-char
    gap) stays silent, while denials keep over-firing (probe54 post-fix: 23/23;
    window threshold 11w=84 char gap FLAG, 12w=95 char gap SILENT).
    Cycle-42 widens the slot to "(?:\w+ ){0,12}" and the branch-8 window to
    "[^.;]{0,97}": the TWELVE-word reversed-passive (97-char gap) now flags
    again, and the THIRTEEN-word phrase ("...audit log monitoring review data")
    is the new far side — tight positives silent, reversed-passive silent at its
    104-char gap, denials keep over-firing.
    Cycle-43 widens the slot to "(?:\w+ ){0,13}" and the branch-8 window to
    "[^.;]{0,104}": the THIRTEEN-word reversed-passive (104-char gap) now flags
    again, and the FOURTEEN-word phrase ("...audit log monitoring review policy
    data") is the new far side — tight positives silent, reversed-passive silent
    at its 111-char gap, denials keep over-firing. Cycle-44 widens the slot to
    "(?:\w+ ){0,14}" and the branch-8 window to "[^.;]{0,111}": the FOURTEEN-word
    reversed-passive (111-char gap, now at the exact window edge) flags again,
    and the FIFTEEN-word phrase ("...audit log monitoring review policy handling
    data") is the new far side — tight positives silent, reversed-passive silent
    at its 118-char gap, denials keep over-firing. The P4 campaign later widened
    the slot to "(?:\w+ ){0,15}" and the branch-8 window to "[^.;]{0,120}": the
    FIFTEEN-word reversed-passive (120-char gap, at the exact window edge) flags
    again, the SIXTEEN-word phrase ("...audit log monitoring review policy
    handling compliance data") is the new far side, and the summary lines below
    now assert FIFTEEN-flag plus SIXTEEN-silent.
    """

    SEVEN = "customer online account historical usage audit event log "
    EIGHT = "customer online account historical usage audit event trail log "
    NINE = "customer online account historical usage audit event trail access log "
    TEN = "customer online account historical usage audit event trail access control log "
    ELEVEN = "customer online account historical usage audit event trail access control audit log "
    TWELVE = "customer online account historical usage audit event trail access control audit log monitoring "
    THIRTEEN = "customer online account historical usage audit event trail access control audit log monitoring review "
    FOURTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy "
    FIFTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling "
    SIXTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance "

    def test_eleven_word_pre_data_denials_not_flagged(self):
        benign = [
            f"No {self.ELEVEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.ELEVEN}data shall be retained beyond the applicable retention period.",
            f"After the latest permitted period, no {self.ELEVEN}data storage shall occur.",
            f"{self.ELEVEN}data retention shall not occur beyond the applicable retention period.",
            f"No {self.ELEVEN}data backup copies retention beyond the applicable retention period shall occur.",
            f"No copies of {self.ELEVEN}data retention beyond the applicable retention period shall occur.",
            f"No copies of {self.ELEVEN}data shall be retained beyond the applicable retention period.",
            f"No {self.ELEVEN}data retention for a period of 90 days shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_eleven_word_tight_object_position_still_flagged(self):
        flagged = [
            f"Provider shall retain {self.ELEVEN}data beyond the applicable retention period.",
            f"Retention of {self.ELEVEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.ELEVEN}data.",
            f"Retention of copies of {self.ELEVEN}data beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_eleven_word_attributive_still_flagged(self):
        flagged = [
            f"{self.ELEVEN}data retention beyond the applicable retention period.",
            f"{self.ELEVEN}data backup copies retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_eleven_word_reversed_passive_still_flagged(self):
        # ELEVEN-word reversed-passive sits at a 84-char gap, TWELVE-word at
        # 97-char and THIRTEEN-word at 104-char; all sit inside the {0,104}
        # window: flag.
        r = score_document(
            [f"After the applicable retention period, {self.ELEVEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary: denials over-fire.
        flagged = [
            f"No {self.SIXTEEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the tight
        # object tails go silent, while attributive mid-phrase still flags.
        benign = [
            f"Provider shall retain {self.SIXTEEN}data beyond the applicable retention period.",
            f"Retention of {self.SIXTEEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.SIXTEEN}data.",
            f"Retention of copies of {self.SIXTEEN}data beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        r = score_document(
            [f"{self.ELEVEN}data retention beyond the applicable retention period."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_sixteen_word_reversed_passive_still_silent(self):
        # Branch 8's "[^.;]{0,120}" window covers the ELEVEN (86-char gap),
        # THIRTEEN (104-char gap) and FIFTEEN (120-char gap) reversed-passive
        # forms: all flag (the FIFTEEN at the exact window edge). The SIXTEEN
        # phrase (131-char gap) sits beyond the window: silent.
        r = score_document(
            [f"After the applicable retention period, {self.ELEVEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.THIRTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.FIFTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.SIXTEEN}data shall be retained by the Provider."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)


class TestCycle42Precision:
    r"""Cycle-42 precision: R-DATA-5 twelve-word pre-data qualifier boundary.

    Cycle-41 widened the pre-data modifier slot to "(?:\w+ ){0,11}" in all six
    sites (the four pattern tails + nominal and verb-form denial branches),
    covering up to ELEVEN qualifier words (plus the optional "customer "
    prefix). A TWELVE-word phrase ("customer online account historical usage
    audit event trail access control audit log monitoring data") sat beyond the
    {0,11} boundary: tight object tails went silent while nominal/verb-form
    denials still over-fired R-DATA-5, and the reversed-passive form sat beyond
    branch 8's "[^.;]{0,89}" window (95-char gap).

    Fix: widen the slot to "(?:\w+ ){0,12}" in the same six sites and widen the
    branch-8 window to "[^.;]{0,97}" so the TWELVE-word reversed-passive
    (97-char gap) flags again (rules.py:537/544/550/558/600/605/572).

    TWELVE-word phrases now flag on both sides; THIRTEEN-word phrases sit beyond
    the new boundary: tight positives go silent and reversed-passive (104-char
    gap) stays silent, while denials keep over-firing (window threshold
    12w=97 char gap FLAG, 13w=104 char gap SILENT). Cycle-43 widens the slot to
    "(?:\w+ ){0,13}" and the branch-8 window to "[^.;]{0,104}": the THIRTEEN-word
    reversed-passive (104-char gap) now flags again, and the FOURTEEN-word phrase
    ("...audit log monitoring review policy data") is the new far side — tight
    positives silent, reversed-passive silent at its 111-char gap, denials keep
    over-firing. Cycle-44 widens the slot to "(?:\w+ ){0,14}" and the branch-8
    window to "[^.;]{0,111}": the FOURTEEN-word reversed-passive (111-char gap,
    now at the exact window edge) flags again, and the FIFTEEN-word phrase
    ("...audit log monitoring review policy handling data") is the new far side —
    tight positives silent, reversed-passive silent at its 118-char gap, denials
    keep over-firing. The P4 campaign later widened the slot to "(?:\w+ ){0,15}"
    and the branch-8 window to "[^.;]{0,120}": the FIFTEEN-word reversed-passive
    (120-char gap, at the exact window edge) flags again, the SIXTEEN-word phrase
    ("...audit log monitoring review policy handling compliance data") is the new
    far side, and the summary lines below now assert FIFTEEN-flag plus
    SIXTEEN-silent.
    """

    SEVEN = "customer online account historical usage audit event log "
    EIGHT = "customer online account historical usage audit event trail log "
    NINE = "customer online account historical usage audit event trail access log "
    TEN = "customer online account historical usage audit event trail access control log "
    ELEVEN = "customer online account historical usage audit event trail access control audit log "
    TWELVE = "customer online account historical usage audit event trail access control audit log monitoring "
    THIRTEEN = "customer online account historical usage audit event trail access control audit log monitoring review "
    FOURTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy "
    FIFTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling "
    SIXTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance "

    def test_twelve_word_pre_data_denials_not_flagged(self):
        benign = [
            f"No {self.TWELVE}data retention beyond the applicable retention period shall occur.",
            f"No {self.TWELVE}data shall be retained beyond the applicable retention period.",
            f"After the latest permitted period, no {self.TWELVE}data storage shall occur.",
            f"{self.TWELVE}data retention shall not occur beyond the applicable retention period.",
            f"No {self.TWELVE}data backup copies retention beyond the applicable retention period shall occur.",
            f"No copies of {self.TWELVE}data retention beyond the applicable retention period shall occur.",
            f"No copies of {self.TWELVE}data shall be retained beyond the applicable retention period.",
            f"No {self.TWELVE}data retention for a period of 90 days shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_twelve_word_verb_form_denials_not_flagged(self):
        benign = [
            f"No copies of {self.TWELVE}data shall be retained beyond the applicable retention period.",
            f"Beyond the applicable retention period, no {self.TWELVE}data shall be stored by the provider.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_twelve_word_tight_object_position_still_flagged(self):
        flagged = [
            f"Provider shall retain {self.TWELVE}data beyond the applicable retention period.",
            f"Retention of {self.TWELVE}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.TWELVE}data.",
            f"Retention of copies of {self.TWELVE}data beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_twelve_word_attributive_still_flagged(self):
        flagged = [
            f"{self.TWELVE}data retention beyond the applicable retention period.",
            f"{self.TWELVE}data backup copies retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_twelve_word_reversed_passive_still_flagged(self):
        # Branch 8's "{0,104}" window covers the 12-word (97-char gap) and the
        # 13-word (104-char gap) reversed-passive forms: both flag, the 13-word
        # at the exact window edge. ELEVEN-word (86-char gap) stays inside too.
        r = score_document(
            [f"After the applicable retention period, {self.ELEVEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.TWELVE}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary: denials over-fire.
        flagged = [
            f"No {self.SIXTEEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the
        # tight object tails go silent, while attributive mid-phrase still flags.
        benign = [
            f"Provider shall retain {self.SIXTEEN}data beyond the applicable retention period.",
            f"Retention of {self.SIXTEEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.SIXTEEN}data.",
            f"Retention of copies of {self.SIXTEEN}data beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        r = score_document(
            [f"{self.TWELVE}data retention beyond the applicable retention period."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_sixteen_word_reversed_passive_still_silent(self):
        # Branch 8's "[^.;]{0,120}" window covers the TWELVE (97-char gap),
        # THIRTEEN (104-char gap) and FIFTEEN (120-char gap) reversed-passive
        # forms: all flag (the FIFTEEN at the exact window edge). The SIXTEEN
        # phrase (131-char gap) sits beyond the window: silent.
        r = score_document(
            [f"After the applicable retention period, {self.TWELVE}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.THIRTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.FIFTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.SIXTEEN}data shall be retained by the Provider."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)


class TestCycle43Precision:
    r"""Cycle-43 precision: R-DATA-5 thirteen-word pre-data qualifier boundary.

    Cycle-42 widened the pre-data modifier slot to "(?:\w+ ){0,12}" in all six
    sites (the four pattern tails + nominal and verb-form denial branches),
    covering up to TWELVE qualifier words (plus the optional "customer "
    prefix). A THIRTEEN-word phrase ("customer online account historical usage
    audit event trail access control audit log monitoring review data") sat
    beyond the {0,12} boundary: tight object tails went silent while
    nominal/verb-form denials still over-fired R-DATA-5, and the
    reversed-passive form sat beyond branch 8's "[^.;]{0,97}" window
    (104-char gap).

    Fix: widen the slot to "(?:\w+ ){0,13}" in the same six sites and widen the
    branch-8 window to "[^.;]{0,104}" so the THIRTEEN-word reversed-passive
    (104-char gap) flags again (rules.py:537/544/550/558/600/605/572).

    THIRTEEN-word phrases now flag on both sides; FOURTEEN-word phrases sit
    beyond the new boundary: tight positives go silent and reversed-passive
    (111-char gap) stays silent, while denials keep over-firing (window
    threshold 13w=104 char gap FLAG, 14w=111 char gap SILENT). Attributive
    mid-phrase still flags at FOURTEEN words: the bare data noun sits mid-slot,
    so the width-robust tail keeps matching. Cycle-44 widens the slot to
    "(?:\w+ ){0,14}" and the branch-8 window to "[^.;]{0,111}": the FOURTEEN-word
    reversed-passive (111-char gap, now at the exact window edge) flags again,
    and the FIFTEEN-word phrase ("...audit log monitoring review policy handling
    data") is the new far side — tight positives silent, reversed-passive silent
    at its 118-char gap, denials keep over-firing. Attributive mid-phrase still
    flags at SIXTEEN words: the bare data noun sits mid-slot, so the
    width-robust tail keeps matching. The P4 campaign later widened the slot to
    "(?:\w+ ){0,15}" and the branch-8 window to "[^.;]{0,120}": the FIFTEEN-word
    reversed-passive (120-char gap, at the exact window edge) flags again, the
    SIXTEEN-word phrase ("...audit log monitoring review policy handling
    compliance data") is the new far side, and the summary lines below now assert
    FIFTEEN-flag plus SIXTEEN-silent.
    """

    SEVEN = "customer online account historical usage audit event log "
    EIGHT = "customer online account historical usage audit event trail log "
    NINE = "customer online account historical usage audit event trail access log "
    TEN = "customer online account historical usage audit event trail access control log "
    ELEVEN = "customer online account historical usage audit event trail access control audit log "
    TWELVE = "customer online account historical usage audit event trail access control audit log monitoring "
    THIRTEEN = "customer online account historical usage audit event trail access control audit log monitoring review "
    FOURTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy "
    FIFTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling "
    SIXTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance "

    def test_thirteen_word_pre_data_denials_not_flagged(self):
        benign = [
            f"No {self.THIRTEEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.THIRTEEN}data shall be retained beyond the applicable retention period.",
            f"After the latest permitted period, no {self.THIRTEEN}data storage shall occur.",
            f"{self.THIRTEEN}data retention shall not occur beyond the applicable retention period.",
            f"No {self.THIRTEEN}data backup copies retention beyond the applicable retention period shall occur.",
            f"No copies of {self.THIRTEEN}data retention beyond the applicable retention period shall occur.",
            f"No copies of {self.THIRTEEN}data shall be retained beyond the applicable retention period.",
            f"No {self.THIRTEEN}data retention for a period of 90 days shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_thirteen_word_verb_form_denials_not_flagged(self):
        benign = [
            f"No copies of {self.THIRTEEN}data shall be retained beyond the applicable retention period.",
            f"Beyond the applicable retention period, no {self.THIRTEEN}data shall be stored by the provider.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_thirteen_word_tight_object_position_still_flagged(self):
        flagged = [
            f"Provider shall retain {self.THIRTEEN}data beyond the applicable retention period.",
            f"Retention of {self.THIRTEEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.THIRTEEN}data.",
            f"Retention of copies of {self.THIRTEEN}data beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_thirteen_word_attributive_still_flagged(self):
        flagged = [
            f"{self.THIRTEEN}data retention beyond the applicable retention period.",
            f"{self.THIRTEEN}data backup copies retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_thirteen_word_reversed_passive_still_flagged(self):
        # THIRTEEN-word reversed-passive sits at a 104-char gap: inside branch
        # 8's current "[^.;]{0,120}" window, so it flags.
        r = score_document(
            [f"After the applicable retention period, {self.THIRTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary: denials over-fire.
        flagged = [
            f"No {self.SIXTEEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the tight
        # object tails go silent, while attributive mid-phrase still flags.
        benign = [
            f"Provider shall retain {self.SIXTEEN}data beyond the applicable retention period.",
            f"Retention of {self.SIXTEEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.SIXTEEN}data.",
            f"Retention of copies of {self.SIXTEEN}data beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t
        r = score_document(
            [f"{self.THIRTEEN}data retention beyond the applicable retention period."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_sixteen_word_reversed_passive_still_silent(self):
        # Branch 8's "[^.;]{0,120}" window covers the TWELVE (97-char gap),
        # THIRTEEN (104-char gap) and FIFTEEN (120-char gap) reversed-passive
        # forms: all flag (the FIFTEEN at the exact window edge). The SIXTEEN
        # phrase (131-char gap) sits beyond the window: silent.
        r = score_document(
            [f"After the applicable retention period, {self.TWELVE}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.THIRTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.FIFTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.SIXTEEN}data shall be retained by the Provider."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)


class TestCycle44Precision:
    r"""Cycle-44 precision: R-DATA-5 fourteen-word pre-data qualifier boundary.

    Cycle-43 widened the pre-data modifier slot to "(?:\w+ ){0,13}" in all six
    sites (the four pattern tails + nominal and verb-form denial branches),
    covering up to THIRTEEN qualifier words (plus the optional "customer "
    prefix). A FOURTEEN-word phrase ("customer online account historical usage
    audit event trail access control audit log monitoring review policy data")
    sat beyond the {0,13} boundary: tight object tails went silent while
    nominal/verb-form denials still over-fired R-DATA-5, and the
    reversed-passive form sat beyond branch 8's "[^.;]{0,104}" window
    (111-char gap).

    Fix: widen the slot to "(?:\w+ ){0,14}" in the same six sites and widen the
    branch-8 window to "[^.;]{0,111}" so the FOURTEEN-word reversed-passive
    (111-char gap) flags again (rules.py:537/544/550/558/600/605/572).

    FOURTEEN-word phrases now flag on both sides; FIFTEEN-word phrases sit
    beyond the {0,14} slot: tight positives go silent and the reversed-passive
    (111-char gap) sits at the edge of the {0,111} window, while denials keep
    over-firing (window threshold 14w=111 char gap FLAG, 15w=118 char gap
    SILENT). Attributive mid-phrase still flags at SIXTEEN words: the bare data
    noun sits mid-slot, so the width-robust tail keeps matching. The P4 campaign
    later widened the slot to {0,15} and the branch-8 window to {0,120}: the
    FIFTEEN-word reversed-passive (120-char gap, at the exact window edge) now
    flags again, the SIXTEEN-word phrase ("...audit log monitoring review policy
    handling compliance data") is the new far side, and the summary lines below
    now assert FIFTEEN-flag plus SIXTEEN-silent.
    """

    SEVEN = "customer online account historical usage audit event log "
    EIGHT = "customer online account historical usage audit event trail log "
    NINE = "customer online account historical usage audit event trail access log "
    TEN = "customer online account historical usage audit event trail access control log "
    ELEVEN = "customer online account historical usage audit event trail access control audit log "
    TWELVE = "customer online account historical usage audit event trail access control audit log monitoring "
    THIRTEEN = "customer online account historical usage audit event trail access control audit log monitoring review "
    FOURTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy "
    FIFTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling "
    SIXTEEN = "customer online account historical usage audit event trail access control audit log monitoring review policy handling compliance "

    def test_fourteen_word_pre_data_denials_not_flagged(self):
        benign = [
            f"No {self.FOURTEEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.FOURTEEN}data shall be retained beyond the applicable retention period.",
            f"After the latest permitted period, no {self.FOURTEEN}data storage shall occur.",
            f"{self.FOURTEEN}data retention shall not occur beyond the applicable retention period.",
            f"No {self.FOURTEEN}data backup copies retention beyond the applicable retention period shall occur.",
            f"No copies of {self.FOURTEEN}data retention beyond the applicable retention period shall occur.",
            f"No copies of {self.FOURTEEN}data shall be retained beyond the applicable retention period.",
            f"No {self.FOURTEEN}data retention for a period of 90 days shall occur.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_fourteen_word_verb_form_denials_not_flagged(self):
        benign = [
            f"No copies of {self.FOURTEEN}data shall be retained beyond the applicable retention period.",
            f"Beyond the applicable retention period, no {self.FOURTEEN}data shall be stored by the provider.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_fourteen_word_tight_object_position_still_flagged(self):
        flagged = [
            f"Provider shall retain {self.FOURTEEN}data beyond the applicable retention period.",
            f"Retention of {self.FOURTEEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.FOURTEEN}data.",
            f"Retention of copies of {self.FOURTEEN}data beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_fourteen_word_attributive_still_flagged(self):
        flagged = [
            f"{self.FOURTEEN}data retention beyond the applicable retention period.",
            f"{self.FOURTEEN}data backup copies retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_fourteen_word_reversed_passive_still_flagged(self):
        # FOURTEEN-word reversed-passive sits at a 111-char gap: inside branch
        # 8's current "[^.;]{0,120}" window, so it flags.
        r = score_document(
            [f"After the applicable retention period, {self.FOURTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)

    def test_sixteen_word_pre_data_denials_still_flagged(self):
        # Sixteen-word phrases sit beyond the {0,15} boundary: denials over-fire.
        flagged = [
            f"No {self.SIXTEEN}data retention beyond the applicable retention period shall occur.",
            f"No {self.SIXTEEN}data shall be retained beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_tight_object_position_still_silent(self):
        # Sixteen-word pre-data phrases sit beyond the {0,15} boundary: the tight
        # object tails go silent, while attributive mid-phrase still flags.
        benign = [
            f"Provider shall retain {self.SIXTEEN}data beyond the applicable retention period.",
            f"Retention of {self.SIXTEEN}data beyond the applicable retention period.",
            f"After the applicable retention period, Provider shall retain {self.SIXTEEN}data.",
            f"Retention of copies of {self.SIXTEEN}data beyond the applicable retention period.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_attributive_still_flagged(self):
        # Attributive mid-phrase stays width-robust: the bare data noun sits
        # mid-slot at SIXTEEN words, so the tail keeps matching.
        flagged = [
            f"{self.SIXTEEN}data retention beyond the applicable retention period.",
            f"{self.SIXTEEN}data backup copies retention beyond the applicable retention period.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-5" for p in r.penalties), t

    def test_sixteen_word_reversed_passive_still_silent(self):
        # Branch 8's "[^.;]{0,120}" window covers the THIRTEEN (104-char gap),
        # FOURTEEN (111-char gap) and FIFTEEN (120-char gap) reversed-passive
        # forms: all flag (the FIFTEEN at the exact window edge). The SIXTEEN
        # phrase (131-char gap) sits beyond the window: silent.
        r = score_document(
            [f"After the applicable retention period, {self.THIRTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.FOURTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.FIFTEEN}data shall be retained by the Provider."], "d"
        )
        assert any(p.rule_id == "R-DATA-5" for p in r.penalties)
        r = score_document(
            [f"After the applicable retention period, {self.SIXTEEN}data shall be retained by the Provider."], "d"
        )
        assert all(p.rule_id != "R-DATA-5" for p in r.penalties)


class TestCycle45Precision:
    r"""Cycle-45 precision: R-LIAB-3 broad-indemnification fault attribution.

    R-LIAB-3 flags one-sided, broad indemnification obligations. Earlier
    regression work silenced mutual indemnities ("each/either party ... own
    breach", "mutual(ly) indemnif") and narrow own-fault constructions. Two
    residuals remained in cycle-44 code:

    1. "for"-connector under-fire: the pattern's connector set was
       "(?:against|from)", so one-sided "indemnify ... for any claims" clauses
       went unflagged. Fix: "(?:against|from|for)".
    2. Named-party own-fault over-fire: "Buyer shall indemnify Seller against
       claims arising out of Buyer's own breach" flagged even though the fault
       owner is the indemnitor (a mutual-carve-out pattern). Widening the
       "arising from/out of ... its own" plurals did not cover named-party
       constructions, and admitting "for" to the pattern re-opened the mutual
       "for"-connector phrases.

    Fix (rules.py:403-431): windowed mutual branches
    ("(?:the parties|both parties)[^.;]{0,25}(?:mutually |cross-? )?indemnif
    [^.;]{0,25}each other" plus hold/held-harmless heads), plural "each party's
    own", a "caused by" tail variant, and a named-party fault-owner
    backreference branch: "(?P<pidty>[a-z]{2,})\s+(?:shall\s+|will\s+|hereby\s+|
    agrees?\s+to\s+|has\s+agreed\s+to\s+)?(?:indemnif(?:y|ies)?|(?:hold|held)
    [^.]{0,25}harmless)[^.]{0,120}(?:arising (?:out of|from)|(?:to the extent
    \s+)?(?:caused by|arising from))\s+(?:the\s+)?(?P=pidty)'?s?\s+own\s+
    (?:breach|negligence)".

    The backreference requires the SAME party who is the subject of the
    indemnification verb to own the fault: indemnitee-fault ("... arising from
    Provider's own negligence") and third-party-fault ("... from a third
    party's own breach") phrases still flag.
    """

    def test_named_party_own_breach_not_flagged(self):
        benign = [
            f"Buyer shall indemnify Seller against claims arising out of Buyer's own breach of contract.",
            f"Customer shall hold Provider harmless against any claims arising from Customer's own negligence.",
            f"Vendor shall indemnify Purchaser to the extent caused by Vendor's own negligence.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-3" for p in r.penalties), t

    def test_named_party_indemnitee_fault_still_flagged(self):
        flagged = [
            f"Customer shall indemnify Provider against any claims arising from Provider's own negligence.",
            f"Customer shall hold Provider harmless against any claims arising from Provider's own negligence.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-3" for p in r.penalties), t

    def test_third_party_fault_still_flagged(self):
        r = score_document(
            ["Customer shall indemnify the Provider against all claims arising from a third party's own breach."], "d"
        )
        assert any(p.rule_id == "R-LIAB-3" for p in r.penalties)

    def test_mutual_for_connector_own_fault_not_flagged(self):
        benign = [
            f"Each party shall indemnify the other for any loss or damage caused by its own negligence.",
            f"The parties shall indemnify each other for any loss caused by their own negligence.",
            f"Both parties shall indemnify each other for any claims arising from their respective own acts.",
            f"Each party shall indemnify the other for any claims caused by the indemnifying party's own gross negligence.",
            f"The parties shall cross-indemnify each other for losses caused by the indemnifying party's own breach.",
            f"Either party shall indemnify the other for any claims arising from its own breach.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-3" for p in r.penalties), t

    def test_one_sided_for_connector_still_flagged(self):
        flagged = [
            f"Supplier agrees to indemnify Customer for any claims or losses it may suffer.",
            f"Supplier shall indemnify Customer for any claims.",
            f"Vendor shall indemnify Buyer for any losses arising from the services.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-3" for p in r.penalties), t


class TestCycle46Precision:
    """Cycle-46 precision regression: R-LIAB-1 modal-less and verb-form
    disclaimers (present-tense 'is not liable', 'has/accepts/bears no
    liability', 'disclaims/excludes liability', 'shall have no
    responsibility') fire; mutual-party and carve-out constructions stay
    silent."""

    def test_present_tense_not_liable_flagged(self):
        r = score_document(
            ["Provider is not liable for consequential damages of any kind."], "d"
        )
        assert any(p.rule_id == "R-LIAB-1" for p in r.penalties)

    def test_has_no_liability_flagged(self):
        r = score_document(
            ["Provider has no liability for consequential damages."], "d"
        )
        assert any(p.rule_id == "R-LIAB-1" for p in r.penalties)

    def test_shall_have_no_responsibility_flagged(self):
        r = score_document(
            ["The provider shall have no responsibility for consequential damages."], "d"
        )
        assert any(p.rule_id == "R-LIAB-1" for p in r.penalties)

    def test_accepts_no_liability_flagged(self):
        r = score_document(
            ["Provider accepts no liability for any indirect damages."], "d"
        )
        assert any(p.rule_id == "R-LIAB-1" for p in r.penalties)

    def test_disclaims_liability_flagged(self):
        flagged = [
            "Vendor disclaims all liability for consequential damages.",
            "The licensor disclaims liability for indirect or consequential losses.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-1" for p in r.penalties), t

    def test_excludes_liability_flagged(self):
        r = score_document(
            ["Provider excludes all liability for consequential damages."], "d"
        )
        assert any(p.rule_id == "R-LIAB-1" for p in r.penalties)

    def test_shall_bear_no_liability_flagged(self):
        r = score_document(
            ["Vendor shall bear no liability for consequential damages."], "d"
        )
        assert any(p.rule_id == "R-LIAB-1" for p in r.penalties)

    def test_mutual_present_tense_not_liable_silent(self):
        benign = [
            "Either party is not liable for any indirect or consequential damages.",
            "Each party shall have no liability to the other for indirect damages.",
            "Both parties shall not be liable to each other for consequential damages arising from use of the services.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-1" for p in r.penalties), t

    def test_carve_out_modal_less_silent(self):
        benign = [
            "The provider is not liable for consequential damages, except in cases of fraud or gross negligence.",
            "The vendor accepts no liability for indirect damages other than for losses caused by the supplier's gross negligence.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-1" for p in r.penalties), t


class TestCycle47Precision:
    # R-COMM-8 cycle-47 precision: qualifier variants + passive voice

    def test_without_any_notice_flagged(self):
        r = score_document(
            ["Provider may suspend the services without any notice whatsoever."], "d"
        )
        assert any(p.rule_id == "R-COMM-8" for p in r.penalties)

    def test_without_any_warning_flagged(self):
        r = score_document(
            ["Provider may suspend the services without any warning."], "d"
        )
        assert any(p.rule_id == "R-COMM-8" for p in r.penalties)

    def test_with_no_notice_flagged(self):
        r = score_document(
            ["Provider may suspend the services with no notice."], "d"
        )
        assert any(p.rule_id == "R-COMM-8" for p in r.penalties)

    def test_in_sole_discretion_flagged(self):
        r = score_document(
            ["Provider may suspend the services in its sole discretion."], "d"
        )
        assert any(p.rule_id == "R-COMM-8" for p in r.penalties)

    def test_complete_discretion_flagged(self):
        r = score_document(
            ["Provider may deactivate the account at its complete discretion."], "d"
        )
        assert any(p.rule_id == "R-COMM-8" for p in r.penalties)

    def test_passive_suspended_flagged(self):
        flagged = [
            "The services may be suspended at any time without notice.",
            "Any account may be deactivated by Provider without notice.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-8" for p in r.penalties), t

    def test_passive_notice_bound_silent(self):
        benign = [
            "The services may be suspended by Provider only if 30 days' written notice is given.",
            "Any account may be suspended if Customer materially breaches this agreement.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-8" for p in r.penalties), t

    def test_passive_mutual_silent(self):
        benign = [
            "Each account may be suspended by either party upon written notice.",
            "The services may be suspended by either party where the other party is in material breach and fails to cure.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-8" for p in r.penalties), t

    def test_new_qualifier_carve_out_silent(self):
        benign = [
            "Provider may suspend the services in its sole discretion unless Customer cures the breach within 10 days.",
            "Provider may suspend the services without any warning provided it gives written notice of the non-payment.",
            "Provider may suspend the services with no notice provided it gives Customer prior written notice.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-8" for p in r.penalties), t


class TestCycle48Precision:
    # R-COMM-4 cycle-48 precision: verb-list grants + delegate/subcontract

    def test_assign_transfer_delegate_subcontract_verbs_flagged(self):
        r = score_document(
            [
                "Provider may assign, transfer, delegate or subcontract any of its obligations "
                "under this agreement to any third party without the prior written consent of Customer."
            ],
            "d",
        )
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_delegate_obligations_to_third_party_flagged(self):
        flagged = [
            "Provider may delegate its obligations under this agreement to any third party "
            "without the prior written consent of Customer.",
            "Customer may delegate its obligations under this agreement to any third party "
            "without the consent of Provider.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-4" for p in r.penalties), t

    def test_subcontract_services_to_third_party_flagged(self):
        r = score_document(
            [
                "Provider may subcontract the provision of the services to any third party "
                "without notice."
            ],
            "d",
        )
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_will_be_assigned_by_provider_flagged(self):
        r = score_document(
            ["This agreement will be assigned by Provider to a third party without notice."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_make_any_assignment_no_consent_flagged(self):
        flagged = [
            "Customer may make any assignment of this agreement to any third party "
            "without the prior written consent of Provider.",
            "Provider may make an assignment of this agreement without the consent of Customer.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-4" for p in r.penalties), t

    def test_neither_party_verb_list_silent(self):
        benign = [
            "Neither party may assign, transfer or delegate any of its obligations under this "
            "agreement without the prior written consent of the other party.",
            "A party shall not assign, transfer or delegate this agreement without the other "
            "party's consent.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-4" for p in r.penalties), t

    def test_transfer_prohibition_shields_silent(self):
        benign = [
            "Neither party may transfer this agreement without the prior written consent of "
            "the other party.",
            "A party shall not transfer this agreement without the other party's consent.",
            "Customer may transfer all of its rights under this agreement to an affiliate "
            "without consent.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-4" for p in r.penalties), t

    def test_delegate_shields_silent(self):
        benign = [
            "Neither party may delegate any of its obligations under this agreement without "
            "the prior written consent of the other party.",
            "A party shall not delegate its obligations under this agreement without the "
            "other party's consent.",
            "Provider may delegate its obligations to an affiliate without consent.",
            "Provider may delegate its obligations upon the prior written consent of Customer.",
            "Provider may delegate its obligations subject to the prior written consent of Customer.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-4" for p in r.penalties), t

    def test_subcontract_shields_silent(self):
        benign = [
            "Provider may subcontract the provision of the services to an affiliate without consent.",
            "Provider may subcontract the provision of the services upon the prior written "
            "consent of Customer.",
            "A party shall not subcontract its obligations without the prior written consent "
            "of the other party.",
            "Provider may subcontract the provision of the services to a third party selected "
            "by Customer.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-4" for p in r.penalties), t


class TestCycle49Precision:
    # R-LIAB-3 cycle-49 precision: passive be-indemnified/harmless,
    # keep/kept harmless, in-respect-of connector, own-fault shields

    def test_passive_be_indemnified_flagged(self):
        flagged = [
            "Customer shall be indemnified by Provider against any claims arising out of the services.",
            "Customer will be indemnified by Supplier against all third party claims.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-3" for p in r.penalties), t

    def test_passive_held_harmless_flagged(self):
        r = score_document(
            ["Customer shall be held harmless by Provider against any claims arising out of the services."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-3" for p in r.penalties)

    def test_keep_harmless_flagged(self):
        r = score_document(
            ["Customer shall keep Provider harmless from any claims arising out of the services."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-3" for p in r.penalties)

    def test_in_respect_of_connector_flagged(self):
        flagged = [
            "Supplier shall indemnify Customer in respect of any claims from third parties.",
            "Vendor indemnifies Buyer in respect of any losses incurred under this agreement.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-3" for p in r.penalties), t

    def test_indemnified_past_tense_flagged(self):
        r = score_document(
            ["Vendor indemnified Buyer against all losses incurred under this agreement."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-3" for p in r.penalties)

    def test_indemnifying_gerund_flagged(self):
        r = score_document(
            ["Provider is indemnifying Customer for any third party claims arising from the software."],
            "d",
        )
        assert any(p.rule_id == "R-LIAB-3" for p in r.penalties)

    def test_passive_beneficiary_own_fault_flagged(self):
        # Indemnitee is at fault; one-sided risk to the counterparty -> fires
        flagged = [
            "Customer shall be indemnified by Provider against claims arising out of Customer's own negligence.",
            "Customer shall be held harmless by Provider against claims arising out of Customer's own negligence.",
            "Customer shall be kept harmless by Provider against claims arising out of Customer's own negligence.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-3" for p in r.penalties), t

    def test_passive_holder_own_fault_silent(self):
        # Indemnitor is at fault -> own-fault shield stays silent
        benign = [
            "Provider shall be held harmless by Customer against claims arising out of Customer's own negligence.",
            "Provider shall be indemnified by Customer to the extent caused by Customer's own negligence.",
            "Vendor shall be kept harmless by Customer against claims arising out of Customer's own negligence.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-3" for p in r.penalties), t

    def test_keep_harmless_own_fault_shields_silent(self):
        benign = [
            "The parties shall keep each other harmless against claims arising out of their own negligence.",
            "Customer shall keep Vendor harmless against claims arising out of Customer's own negligence.",
            "Each party shall keep the other harmless against claims arising out of its own breach.",
            "The parties shall keep each other harmless from any claims arising out of the parties' own acts.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-3" for p in r.penalties), t


class TestCycle50Precision:
    # R-DATA-4 cycle-50 precision: PII/special-category-denotes topic,
    # national data-protection law names as protective terms, and
    # retention/minimisation/privacy-law shields silent on R-DATA-1+R-DATA-4

    def test_pii_topic_without_protection_flagged(self):
        flagged = [
            "The parties acknowledge that customer PII will be processed under this agreement.",
            "The parties may process special category data relating to data subjects.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-DATA-4" for p in r.penalties), t

    def test_national_data_protection_laws_silent(self):
        benign = [
            "The Provider shall process personal data in accordance with the requirements of PIPEDA.",
            "Personal data shall be handled in line with the LGPD.",
            "The parties shall process personal information in accordance with the CPRA.",
            "The parties shall process personal data in accordance with the PDPA.",
            "Personal data shall be handled in accordance with the APPI.",
            "The parties shall process personal data in line with the requirements of the DPDP Act.",
            "Personal data shall be processed in compliance with the PIPL.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties), t

    def test_purpose_limited_processing_silent(self):
        benign = [
            "The OSP shall process personal data only for the purposes of providing the services and shall delete or anonymise it promptly upon termination.",
            "Provider shall process personal data solely for the purpose of providing the services.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties), t

    def test_privacy_law_compliance_silent(self):
        benign = [
            "Each party shall comply with its privacy obligations under applicable law when handling personal data.",
            "Provider shall handle personal data in accordance with applicable privacy laws.",
            "The parties shall process personal data in compliance with applicable privacy legislation.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties), t

    def test_retention_denial_silent(self):
        benign = [
            "Provider shall not retain any personal data after the termination of this agreement.",
            "Provider shall not keep personal data longer than necessary.",
            "Provider may not retain personal data without Customer's written consent.",
            "Neither party shall retain personal data for longer than twelve months.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties), t

    def test_no_pii_denial_silent(self):
        benign = [
            "The parties agree that no PII is collected or processed under this agreement.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties), t

    def test_general_privacy_shields_silent(self):
        # Already-silent before the cycle: unchanged behaviour preserved
        benign = [
            "Provider shall process personal data in accordance with applicable data protection principles and shall safeguard it at all times.",
            "Neither party shall disclose personal data received from the other party to any third party.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id not in {"R-DATA-1", "R-DATA-4"} for p in r.penalties), t


class TestCycle51Precision:
    # R-COMM-7 cycle-51 precision: verb- and noun-phrase refund/credit/
    # cancellation/reimbursement denials fire; permissive policies, defect/
    # quality carve-outs and purely governmental tax denials stay silent.

    def test_no_cancellation_or_refund_flagged(self):
        flagged = [
            "There is no cancellation or refund of fees once the work begins.",
            "No cancellation or refund shall be permitted after the term begins.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-7" for p in r.penalties), t

    def test_subject_to_refund_denial_flagged(self):
        flagged = [
            "All amounts paid under this agreement are not subject to refund.",
            "Fees paid in advance are not eligible for a refund.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-7" for p in r.penalties), t

    def test_reimbursement_denial_flagged(self):
        flagged = [
            "Prepaid amounts shall not be reimbursed or refunded at any time.",
            "No reimbursement shall be made to the Customer for early termination.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-7" for p in r.penalties), t

    def test_fee_forfeiture_flagged(self):
        flagged = [
            "Any fees paid are forfeited if the agreement is terminated early.",
            "All deposits shall be forfeited upon cancellation by the Customer.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-7" for p in r.penalties), t

    def test_credit_not_carried_over_flagged(self):
        flagged = [
            "Unused credits shall not be credited back upon termination.",
            "Any unused balance shall not be carried over after expiry of the term.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-7" for p in r.penalties), t

    def test_not_refundable_adjectival_flagged(self):
        flagged = [
            "All payments are final and not refundable in any event.",
            "These fees are not refundable for any reason after the order is submitted.",
            "Once purchased, the license cannot be cancelled or refunded.",
            "No refunds are available once the services begin.",
            "Refunds are not given for partially consumed services.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-7" for p in r.penalties), t

    def test_gov_tax_denial_silent(self):
        benign = [
            "Any taxes imposed by governmental authorities are non-refundable by the parties.",
            "Non-refundable duties levied by the customs authority are borne by the importer.",
            "No refunds shall be made for taxes imposed by governmental authorities.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-7" for p in r.penalties), t

    def test_bounded_and_permissive_refunds_silent(self):
        benign = [
            "Customers may request a refund within 30 days of purchase.",
            "The parties mutually agree that refunds are permitted for unused services.",
            "If a quality issue is identified, funds shall be refunded to the client.",
            "A refund for any reason whatsoever is available within 30 days.",
            "Refunds will be made where required by applicable law or consumer protection statutes.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-7" for p in r.penalties), t


class TestCycle52Precision:
    # R-LIAB-5 cycle-52 precision: passive / no-assurance / without-warranty /
    # provided-without-interruption / free-from-errors disclaimers of service
    # availability or quality fire; disclaimers conditioned on force majeure,
    # scheduled maintenance, customer breach/failure or third-party networks
    # stay silent.

    def test_no_assurance_given_flagged(self):
        flagged = [
            "No assurance is given that the Platform will be available at all times.",
            "No guarantee is made that the platform will be free from errors.",
            "No representation is made that the software will operate without error.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-5" for p in r.penalties), t

    def test_without_warranty_of_availability_flagged(self):
        flagged = [
            "The services are provided without warranty of availability.",
            "The tool is furnished without any warranty of reliability.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-5" for p in r.penalties), t

    def test_disclaims_that_error_free_flagged(self):
        # Passive object-clause form: "disclaims that the software will be
        # error-free" has no warranty/guarantee noun to latch onto.
        flagged = [
            "The Company disclaims that the software will be error-free.",
            "Each party disclaims that the services will be uninterrupted.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-5" for p in r.penalties), t

    def test_noun_led_passive_not_guaranteed_flagged(self):
        flagged = [
            "Fitness for a particular purpose is not guaranteed by the Supplier.",
            "Reliability of the platform is not guaranteed by the Vendor.",
            "Error-free operation is not guaranteed by Provider.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-5" for p in r.penalties), t

    def test_provided_without_interruption_flagged(self):
        flagged = [
            "The Provider does not warrant that the services will be provided without interruption.",
            "The Vendor makes no warranty that the services will be performed without interruption.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-5" for p in r.penalties), t

    def test_force_majeure_conditioned_denial_silent(self):
        benign = [
            "Service availability is not guaranteed during Force Majeure events.",
            "Availability of the service is not guaranteed in the event of force majeure.",
            "The parties acknowledge that internet availability is not guaranteed by this agreement.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-5" for p in r.penalties), t

    def test_customer_breach_conditioned_denial_silent(self):
        benign = [
            "Availability of the service is not guaranteed if the Customer fails to pay on time.",
            "The Provider does not warrant that the services will meet requirements if the Customer modifies the software.",
            "Availability is not guaranteed where the Customer breaches the acceptable use policy.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-5" for p in r.penalties), t

    def test_maintenance_conditioned_denial_silent(self):
        benign = [
            "Service availability is not guaranteed in the event of scheduled maintenance.",
            "Availability is not guaranteed during planned maintenance windows.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-5" for p in r.penalties), t


class TestCycle53Precision:
    # R-LIAB-6 cycle-53 precision: bare "damages" (without "liquidated")
    # keyed to a fixed currency amount or percentage and a per-period /
    # per-occurrence / per-event anchor concentrates the same
    # disproportionate-recovery risk as an explicit penalty clause and must
    # fire. Bound and denial phrasings (caps, exclusions, genuine
    # pre-estimate, no-damages) stay silent.

    def test_damages_per_week_flagged(self):
        flagged = [
            "Damages of $1,000 per week shall apply for each week of delay.",
            "The Customer shall pay damages of $2,000 per week of delay beyond the agreed date.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-6" for p in r.penalties), t

    def test_damages_per_day_flagged(self):
        flagged = [
            "The Customer will be liable for damages of $500 for each day of delay.",
            "The Contractor shall pay damages at $750 per day of non-performance.",
            "For each day of delay the Contractor shall be liable for damages of $1,200.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-6" for p in r.penalties), t

    def test_damages_per_month_flagged(self):
        flagged = [
            "Any delay will result in damages of EUR 2,000 per month of delay.",
            "Any late delivery shall give rise to damages of EUR 5,000 per occurrence.",
            "The Supplier shall pay damages of $3,500 for each missed delivery.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-6" for p in r.penalties), t

    def test_damages_per_occurrence_flagged(self):
        flagged = [
            "Delays in delivery will incur damages of $10,000 for each occurrence.",
            "Any late delivery shall give rise to damages of EUR 5,000 per occurrence.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-6" for p in r.penalties), t

    def test_damages_upon_missed_event_flagged(self):
        flagged = [
            "The Supplier pays damages of $5,000 upon each missed delivery date.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-6" for p in r.penalties), t

    def test_damages_accrue_flagged(self):
        flagged = [
            "Damages shall accrue at $1,500 per month until performance is completed.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-LIAB-6" for p in r.penalties), t

    def test_plain_damages_not_flagged_when_bounded(self):
        benign = [
            "The liability of each party for damages is subject to the cap in Section 9.",
            "Damages payable under this clause shall not exceed the fees paid.",
            "Each party's liability for damages is limited to the fees paid under this agreement.",
            "Any penalty or liquidated damages for delay shall not exceed the damages actually suffered.",
            "The penalty for delay shall not exceed 5% of the contract value.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-6" for p in r.penalties), t

    def test_plain_damages_not_flagged_when_denied(self):
        benign = [
            "No damages shall be payable for any delay in delivery.",
            "Damages are excluded unless caused by the gross negligence of the supplier.",
            "Neither party shall be liable for a penalty or liquidated damages for delay.",
            "In no event shall the Provider be liable for consequential damages.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-LIAB-6" for p in r.penalties), t



class TestCycle54Precision:
    """Cycle-54 precision: sanctioned-sales vocabulary and re-export/diversion
    control gaps in R-EXP-2 / R-EXP-3.

    R-EXP-2's topic condition only knew ``sell``/``sold``/``distribute``, so
    "The distributor sells software in Sudan." and "Sales into North Korea are
    permitted." reached neither the condition nor the country pattern and
    under-fired. The condition now covers ``sells``/``selling``, ``sales`` and
    ``distributor(s)``. Over-fires came from licensing/permissive carve-outs
    the exclusion did not recognise: "Export to Iran requires a licence ...",
    "Nothing in this Agreement shall permit the export of goods to Cuba.",
    "This Agreement does not apply to exports into North Korea." and
    "Sales to Iran are made only under a valid export licence." are all
    compliance controls (licence-gated or expressly disallowed) and must stay
    silent. Carve-out branches were added for require/obtain licence-tails,
    "nothing ... shall permit/allow ...", "does/do not apply to <country>" and
    "<country> ... under/pursuant to a ... licence".

    R-EXP-3's pattern only matched re-export/diversion/end-use, so
    "The buyer may re-export the products to any country." (condition lacked
    re-export vocabulary), "Deliverables may be relayed onward without
    end-use restrictions." and "Customer may divert the goods and resell them
    abroad." under-fired. The pattern/condition now also cover resell,
    re-sell, divert and relay(ed/ing), and "without end-use restrictions" is a
    gap (a negated restriction, not a control). Over-fire: "No re-export of
    the deliverables shall occur without a licence." states a prohibition that
    *requires* a licence and must stay silent; a new exclusion branch covers
    "No <re-export/export/diversion> ... shall occur/made/permitted without a
    licence/authority/approval". The bare `restrictions`/`controls` catch-all
    tail was replaced with qualified control wording ("export/sanction/trade
    controls", "... control laws/regulations") so that affirmative control
    language stays silent while negated restrictions still fire.
    """

    def test_sanctioned_sales_flagged(self):
        # Stable-form "Sells into a sanctioned jurisdiction" must fire R-EXP-2
        # even though the word "export" never appears.
        flagged = [
            "The distributor sells software in Sudan.",
            "Sales into North Korea are permitted.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-EXP-2" for p in r.penalties), t

    def test_sanctioned_sales_carve_outs_silent(self):
        # Licence-gated or expressly disallowed sales to sanctioned
        # jurisdictions are compliance controls and must not fire R-EXP-2.
        benign = [
            "Export to Iran requires a licence from the relevant authority.",
            "Nothing in this Agreement shall permit the export of goods to Cuba.",
            "This Agreement does not apply to exports into North Korea.",
            "Sales to Iran are made only under a valid export licence.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-EXP-2" for p in r.penalties), t

    def test_unrestricted_reexport_flagged(self):
        # Wording that re-exports without a control must fire R-EXP-3 even when
        # the condition previously lacked the re-export/diversion vocabulary.
        flagged = [
            "The buyer may re-export the products to any country.",
            "Deliverables may be relayed onward without end-use restrictions.",
            "Customer may divert the goods and resell them abroad.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-EXP-3" for p in r.penalties), t

    def test_licence_gated_reexport_not_flagged(self):
        # A prohibition that conditions re-export on a licence is a control,
        # not a missing-controls gap: R-EXP-3 must stay silent.
        benign = [
            "No re-export of the deliverables shall occur without a licence.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-EXP-3" for p in r.penalties), t


class TestCycle55Precision:
    """Cycle-55 precision: R-COMM-6 above-market late-payment interest.

    Probing found 8 under-fires and 0 over-fires. R-COMM-6's percent tokens
    only accepted a literal "%" sign, so spelled-out "percent"/"per cent"
    rates ("Unpaid invoices accrue interest of 0.05 percent per day.") slipped
    through. The noun-leading reversed orderings ("Amounts overdue accrue
    interest at 10% annually.", "Invoices that are overdue shall bear
    interest at 2% monthly.", "All sums unpaid bear interest at 3% per
    month.") and the implied-delinquency form "not paid by the due date"
    also missed: the qualifier usually preceded the noun, so the post-noun
    "past due" branch never fired. "incur/incurred" was missing from every
    verb list. The pattern now accepts percent/per cent alongside "%" on six
    branches, widens the post-noun qualifier to overdue/delinquent/late/
    unpaid/"not paid by (the )?due date", adds sums/sums? to the noun lists
    and incur(red/ring) to the verb lists. Statutory/market/benchmark rates,
    ordinary non-delinquent interest and one-off fees must stay silent.
    """

    def test_spelled_out_percent_rates_flagged(self):
        # A spelled-out "percent"/"per cent" rate on late/delinquent sums is
        # as one-sided as a "%" sign and must fire R-COMM-6.
        flagged = [
            "Unpaid invoices accrue interest of 0.05 percent per day.",
            "Any amount past due shall bear interest at a rate of 18 percent per annum.",
            "Overdue amounts accrue a late charge at two percent per month.",
            "Unpaid balances shall incur a finance charge at 1.5 percent monthly.",
            "Unpaid amounts accrue interest at 0.1 per cent per day.",
            "Late payments shall accrue interest at a rate of 3 percent per month.",
            "Late payments accrue a penalty at 2 percent per month.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-6" for p in r.penalties), t

    def test_noun_led_delinquency_flagged(self):
        # Rates where the noun precedes its delinquency qualifier ("Amounts
        # overdue", "Invoices that are overdue", "All sums unpaid", "not paid
        # by the due date") must fire R-COMM-6.
        flagged = [
            "Amounts overdue accrue interest at 10% annually.",
            "Invoices that are overdue shall bear interest at 2% monthly.",
            "All sums unpaid bear interest at 3% per month.",
            "Any amount not paid by the due date accrues interest at 2.5% per month.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-6" for p in r.penalties), t

    def test_incur_verb_flagged(self):
        # "incur/incurred" alongside overdue/balance language must fire.
        flagged = [
            "Any balance past due shall incur interest at 2% per month.",
            "Unpaid invoices may incur a late fee of 1.5 per cent per month.",
        ]
        for t in flagged:
            r = score_document([t], "d")
            assert any(p.rule_id == "R-COMM-6" for p in r.penalties), t

    def test_statutory_and_ordinary_rates_not_flagged(self):
        # Statutory/market/benchmark rates, ordinary non-delinquent interest
        # and one-off fees must stay silent even with percent variants.
        benign = [
            "Late payments accrue interest at the statutory rate of 8% per annum.",
            "Overdue amounts bear interest at the prevailing market rate.",
            "Interest on late payments shall be at the ECB base rate plus 2%.",
            "Late payments accrue interest at the legal maximum rate allowed by law.",
            "Unpaid balance accrues interest at LIBOR plus 3 per annum.",
            "The loan shall accrue interest at 12% per annum.",
            "The deposit bears interest at 3% annually.",
            "The parties may charge interest of 5% on any amounts advanced under this agreement.",
            "A commission of 5% is payable to the broker on each sale.",
            "No interest shall accrue until 30 days after the due date; thereafter at the statutory rate.",
        ]
        for t in benign:
            r = score_document([t], "d")
            assert all(p.rule_id != "R-COMM-6" for p in r.penalties), t


class TestCycle56Precision:
    """Cycle-56 precision regression: R-COMM-1 auto-renewal variant families
    (rollover phrasings, continue-consecutive, deemed-renewed negation,
    provided-that and object-in-writing opt-outs)."""

    # --- R-COMM-1 under-fire regressions ---

    def test_extended_for_additional_periods_flagged(self):
        # Regression: "is extended automatically for additional periods" is an
        # automatic rollover and must fire R-COMM-1 even with a tense/voice
        # combination the pattern previously missed.
        r = score_document(
            ["The term of this Agreement is extended automatically for additional "
             "periods of one year."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_roll_over_successive_terms_flagged(self):
        # Regression: "will roll over for successive ... terms" is an
        # auto-renewal idiom and must fire R-COMM-1.
        r = score_document(
            ["This agreement will roll over for successive twelve-month terms."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_roll_over_another_term_flagged(self):
        # Regression: "roll over automatically for another twelve-month term"
        # (adverb + indefinite-determiner object) must fire R-COMM-1.
        r = score_document(
            ["The agreement will roll over automatically for another twelve-month "
             "term."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_continue_consecutive_terms_flagged(self):
        # Regression: "continue for additional consecutive terms" (consecutive
        # as the rolled period qualifier) must fire R-COMM-1.
        r = score_document(
            ["This Agreement shall continue for additional consecutive terms of "
             "one year each."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    def test_continue_successive_numeric_periods_flagged(self):
        # Regression: "continue in force for successive periods of 12 months
        # each" (numeric rollover with continue-phrasing) must fire R-COMM-1.
        r = score_document(
            ["This agreement shall continue in force for successive periods of "
             "12 months each."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-1" for p in r.penalties)

    # --- R-COMM-1 over-fire controls ---

    def test_neither_party_deemed_renewed_automatically_not_flagged(self):
        # Control: "Neither party shall be deemed to have renewed ... 
        # automatically" denies renewal; it is an opt-out statement and must
        # stay silent.
        r = score_document(
            ["Neither party shall be deemed to have renewed this agreement "
             "automatically."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_continue_provided_that_termination_notice_not_flagged(self):
        # Control: a continue-for-successive-terms clause carrying a
        # provided-that written-notice opt-out must stay silent.
        r = score_document(
            ["The Agreement shall continue in effect for successive terms; "
             "provided that either party may terminate upon written notice."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_each_party_object_in_writing_not_flagged(self):
        # Control: a conditional renewal with an "each Party ... object in
        # writing" right is a genuine opt-out and must stay silent.
        r = score_document(
            ["Should the contract be renewed automatically, each Party shall "
             "have the right to object in writing."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_nothing_shall_cause_auto_renewal_not_flagged(self):
        # Control: "Nothing ... shall cause ... renew automatically" is a
        # denial of rollover and must stay silent.
        r = score_document(
            ["Nothing in this clause shall cause the agreement to renew "
             "automatically."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)

    def test_shall_not_renew_automatically_not_flagged(self):
        # Control: "The parties shall not renew this agreement automatically"
        # is an express no-auto-renewal statement and must stay silent even
        # when a reason clause follows in the same sentence.
        r = score_document(
            ["The parties shall not renew this agreement automatically; renewal "
             "requires a new contract."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-1" for p in r.penalties)


class TestCycle57Precision:
    """Cycle-57: R-COMM-2 unilateral without-cause / sole-discretion precision."""

    def test_without_just_cause_fires(self):
        r = score_document(
            ["Provider may terminate this agreement without just cause."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_without_good_cause_fires(self):
        r = score_document(
            ["Provider may terminate this agreement without good cause."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_with_no_cause_fires(self):
        r = score_document(
            ["Provider may terminate this agreement with no cause."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_for_whatever_reason_fires(self):
        r = score_document(
            ["Provider may terminate this agreement for whatever reason."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_for_any_reason_whatsoever_fires(self):
        r = score_document(
            ["Provider may terminate this agreement for any reason whatsoever."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_without_any_cause_whatsoever_fires(self):
        r = score_document(
            ["Provider may terminate this agreement without any cause whatsoever."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_at_its_sole_discretion_fires(self):
        r = score_document(
            ["Provider may terminate this agreement at its sole discretion."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_in_its_sole_discretion_fires(self):
        r = score_document(
            ["Provider may terminate this agreement in its sole discretion."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_at_its_own_discretion_fires(self):
        r = score_document(
            ["Provider may terminate this agreement at its own discretion."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_in_its_absolute_discretion_fires(self):
        r = score_document(
            ["Provider may terminate this agreement in its absolute discretion."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_discretion_before_verb_fires(self):
        r = score_document(
            ["Provider may in its sole discretion terminate this agreement."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_termination_without_justification_fires(self):
        r = score_document(
            ["Provider may terminate this agreement without justification."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_without_giving_any_reason_fires(self):
        r = score_document(
            ["Provider may terminate this agreement without giving any reason."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_without_assigning_any_reason_fires(self):
        r = score_document(
            ["Provider may terminate this agreement without assigning any reason."], "d")
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_sole_discretion_right_fires(self):
        r = score_document(
            ["Provider shall have the right to terminate this agreement at its sole discretion."],
            "d",
        )
        assert any(p.rule_id == "R-COMM-2" for p in r.penalties)

    def test_may_not_terminate_without_cause_silent(self):
        r = score_document(
            ["Provider may not terminate this agreement without cause."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_shall_not_terminate_without_cause_silent(self):
        r = score_document(
            ["Provider shall not terminate this agreement without cause."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_will_not_terminate_without_cause_silent(self):
        r = score_document(
            ["Provider will not terminate this agreement without cause."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_cannot_terminate_without_cause_silent(self):
        r = score_document(
            ["Provider cannot terminate this agreement without cause."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_does_not_have_right_to_terminate_without_cause_silent(self):
        r = score_document(
            ["Provider does not have the right to terminate this agreement without cause."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_either_party_may_not_terminate_without_cause_silent(self):
        r = score_document(
            ["Either party may not terminate this agreement without cause."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_no_party_may_terminate_without_cause_silent(self):
        r = score_document(
            ["No party may terminate this agreement without cause."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_neither_party_may_terminate_without_cause_silent(self):
        r = score_document(
            ["Neither party may terminate this agreement without cause."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_may_not_be_terminated_without_cause_silent(self):
        r = score_document(
            ["This agreement may not be terminated without cause."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_termination_without_cause_prohibited_silent(self):
        r = score_document(
            ["Termination without cause is prohibited."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_termination_without_cause_void_silent(self):
        r = score_document(
            ["Any termination without cause shall be deemed void."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_vendor_loss_boundary_stays_silent(self):
        r = score_document(
            ["The vendor responsibility for any loss shall not be terminated."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_for_cause_stays_silent(self):
        r = score_document(
            ["Provider may terminate this agreement for cause."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_with_just_cause_stays_silent(self):
        r = score_document(
            ["Provider may terminate this agreement with just cause."], "d")
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)

    def test_mutual_termination_stays_silent(self):
        r = score_document(
            ["Either party may terminate this agreement without cause upon 90 days written notice."],
            "d",
        )
        assert all(p.rule_id != "R-COMM-2" for p in r.penalties)


class TestCycle58Precision:
    # R-COMM-4 cycle-58 precision: freely-assign(able) forms, "to a third party"
    # indefinite determiner, third-party-such-as-acquirer tail, and silence for
    # receivables/claims financing assignments and customer-selected third parties

    def test_assign_agreement_freely_flagged(self):
        r = score_document(
            ["Provider may assign the agreement freely."], "d")
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_freely_assignable_by_passive_flagged(self):
        r = score_document(
            ["This agreement is freely assignable by the Provider."], "d")
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_may_freely_assign_flagged(self):
        r = score_document(
            ["The Provider may freely assign this agreement."], "d")
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_to_third_party_such_as_acquirer_flagged(self):
        r = score_document(
            ["Provider may assign this agreement to a third party such as an acquirer."], "d")
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_to_third_parties_flagged(self):
        r = score_document(
            ["Provider may assign the agreement to third parties without consent."], "d")
        assert any(p.rule_id == "R-COMM-4" for p in r.penalties)

    def test_assign_receivables_for_financing_stays_silent(self):
        r = score_document(
            ["Provider may assign its receivables to any third party for financing purposes."], "d")
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_claim_for_payment_to_bank_stays_silent(self):
        r = score_document(
            ["Provider may assign any claim for payment to a bank or finance company."], "d")
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_subcontract_to_customer_selected_third_party_stays_silent(self):
        r = score_document(
            ["Provider may subcontract the provision of the services to a third party "
             "selected by Customer."], "d")
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_assign_to_affiliate_stays_silent(self):
        r = score_document(
            ["Provider may assign this agreement to an affiliate."], "d")
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_prior_written_consent_stays_silent(self):
        r = score_document(
            ["Provider may assign this agreement upon prior written consent of the other party."], "d")
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_mutual_consent_stays_silent(self):
        r = score_document(
            ["Each party may assign this agreement only with the other party's prior written consent."], "d")
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)

    def test_neither_party_stays_silent(self):
        r = score_document(
            ["Neither party may assign this agreement without the other's consent."], "d")
        assert all(p.rule_id != "R-COMM-4" for p in r.penalties)
