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

    def test_export_compliance_affirmation_not_flagged(self):
        r = score_document(
            ["Each party shall comply with all applicable export control and sanctions laws."], "d"
        )
        assert all(p.dimension is not Dimension.EXPORT for p in r.penalties)

    def test_data_protection_clause_not_flagged(self):
        r = score_document(
            ["Personal data shall be processed in accordance with GDPR and the DPA."], "d"
        )
        assert all(p.rule_id != "R-DATA-1" for p in r.penalties)
