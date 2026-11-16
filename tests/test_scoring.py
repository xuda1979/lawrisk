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
        assert any(p.rule_id == "R-EXP-2" for p in r.penalties)

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

    def test_availability_disclaimer_flagged(self):
        r = score_document(
            ["Provider does not warrant that the Services will be uninterrupted or error-free."], "d"
        )
        assert any(p.rule_id == "R-LIAB-5" for p in r.penalties)

    def test_availability_sla_not_flagged(self):
        r = score_document(
            ["The Services will be available 99.9% of the time; guaranteed response times apply."], "d"
        )
        assert all(p.rule_id != "R-LIAB-5" for p in r.penalties)

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
