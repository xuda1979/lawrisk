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
