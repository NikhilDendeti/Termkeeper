"""Tests for `evaluation.selectors.score_risk_severity` (tasks 5.1, 5.2, 5.3)."""

import json

import pytest

import evaluation.selectors as evaluation_selectors
from contracts.tests.factories import ClauseFactory, ContractFactory
from evaluation.selectors import compute_manifest_hash, score_risk_severity
from evaluation.tests.factories import EvalLabelFactory
from risk_scoring.models import SeverityChoices
from risk_scoring.tests.factories import RiskAssessmentFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def heldout_dataset(tmp_path, monkeypatch):
    """A dataset_version with a fully-controlled manifest for isolated scoring tests."""
    monkeypatch.setattr(evaluation_selectors, "_FIXTURES_ROOT", tmp_path)

    def _make_manifest(engagement_ids: list[str]) -> None:
        manifest_dir = tmp_path / "eval" / "unit"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "heldout_manifest.json").write_text(
            json.dumps(
                {
                    "dataset_version": "unit",
                    "heldout_engagement_ids": engagement_ids,
                    "manifest_sha256": compute_manifest_hash(engagement_ids),
                }
            ),
            encoding="utf-8",
        )

    return _make_manifest


def _labeled_clause(*, engagement_id, risky, severity, needs_human_review=False):
    contract = ContractFactory(engagement_id=engagement_id)
    clause = ClauseFactory(contract=contract)
    EvalLabelFactory(
        contract=contract,
        clause=clause,
        ground_truth_value={
            "clause_type": "payment_schedule",
            "risky": risky,
            "severity": severity,
            "rationale": "test rationale naming a mechanism",
            "needs_human_review": needs_human_review,
        },
    )
    return contract, clause


class TestBinaryComparisonDrivesTheMetric:
    """Requirement: Binary comparison drives the metric (task 5.1)."""

    def test_tp_fp_fn_tn_classification_matches_a_hand_computed_example(self, heldout_dataset):
        # TP: risky=True, predicted != low
        _, tp_clause = _labeled_clause(engagement_id="unit-001", risky=True, severity=4)
        RiskAssessmentFactory(clause=tp_clause, severity=SeverityChoices.HIGH)

        # FP: risky=False, predicted != low
        _, fp_clause = _labeled_clause(engagement_id="unit-002", risky=False, severity=1)
        RiskAssessmentFactory(clause=fp_clause, severity=SeverityChoices.MEDIUM)

        # FN: risky=True, predicted == low
        _, fn_clause = _labeled_clause(engagement_id="unit-003", risky=True, severity=5)
        RiskAssessmentFactory(clause=fn_clause, severity=SeverityChoices.LOW)

        # TN: risky=False, predicted == low
        _, tn_clause = _labeled_clause(engagement_id="unit-004", risky=False, severity=1)
        RiskAssessmentFactory(clause=tn_clause, severity=SeverityChoices.LOW)

        heldout_dataset(["unit-001", "unit-002", "unit-003", "unit-004"])

        scores = score_risk_severity(dataset_version="unit")

        assert scores.true_positives == 1
        assert scores.false_positives == 1
        assert scores.false_negatives == 1
        assert scores.true_negatives == 1
        assert scores.precision == pytest.approx(0.5)
        assert scores.recall == pytest.approx(0.5)
        assert scores.f1 == pytest.approx(0.5)


class TestAmbiguousClausesExcludedFromTheBinaryMetric:
    """Requirement: needs_human_review scored as a separate recall metric (task 5.2)."""

    def test_needs_human_review_labeled_clause_never_contributes_to_binary_f1(
        self, heldout_dataset
    ):
        _, hr_clause = _labeled_clause(
            engagement_id="unit-010", risky=True, severity=5, needs_human_review=True
        )
        RiskAssessmentFactory(clause=hr_clause, severity=SeverityChoices.NEEDS_HUMAN_REVIEW)

        heldout_dataset(["unit-010"])

        scores = score_risk_severity(dataset_version="unit")

        assert scores.scored_clause_count == 0
        assert scores.true_positives == 0
        assert scores.false_positives == 0
        assert scores.false_negatives == 0
        assert scores.true_negatives == 0
        assert scores.human_review_clause_count == 1
        assert scores.human_review_recall == pytest.approx(1.0)

    def test_human_review_recall_is_zero_when_pipeline_never_flags_it(self, heldout_dataset):
        _, hr_clause = _labeled_clause(
            engagement_id="unit-011", risky=True, severity=5, needs_human_review=True
        )
        RiskAssessmentFactory(clause=hr_clause, severity=SeverityChoices.CRITICAL)

        heldout_dataset(["unit-011"])

        scores = score_risk_severity(dataset_version="unit")

        assert scores.human_review_recall == pytest.approx(0.0)


class TestPartialCreditForOffByOneSeverity:
    """Requirement: Partial credit for off-by-one severity (task 5.3)."""

    def test_off_by_one_prediction_scores_exactly_half(self, heldout_dataset):
        # Labeled severity 5 (five-point scale); predicted "high" maps to 4
        # on evaluation.selectors.SEVERITY_TO_FIVE_POINT_SCALE - a diff of 1.
        _, clause = _labeled_clause(engagement_id="unit-020", risky=True, severity=5)
        RiskAssessmentFactory(clause=clause, severity=SeverityChoices.HIGH)

        heldout_dataset(["unit-020"])

        scores = score_risk_severity(dataset_version="unit")

        assert scores.severity_calibration_score == pytest.approx(0.5)

    def test_exact_match_scores_one(self, heldout_dataset):
        # Labeled severity 5 maps exactly to predicted "critical" (5).
        _, clause = _labeled_clause(engagement_id="unit-021", risky=True, severity=5)
        RiskAssessmentFactory(clause=clause, severity=SeverityChoices.CRITICAL)

        heldout_dataset(["unit-021"])

        scores = score_risk_severity(dataset_version="unit")

        assert scores.severity_calibration_score == pytest.approx(1.0)

    def test_far_off_prediction_scores_zero(self, heldout_dataset):
        # Labeled severity 5 vs predicted "low" (1) - diff of 4.
        _, clause = _labeled_clause(engagement_id="unit-022", risky=True, severity=5)
        RiskAssessmentFactory(clause=clause, severity=SeverityChoices.LOW)

        heldout_dataset(["unit-022"])

        scores = score_risk_severity(dataset_version="unit")

        assert scores.severity_calibration_score == pytest.approx(0.0)

    def test_calibration_score_is_never_folded_into_f1(self, heldout_dataset):
        _, clause = _labeled_clause(engagement_id="unit-023", risky=True, severity=5)
        RiskAssessmentFactory(clause=clause, severity=SeverityChoices.HIGH)
        heldout_dataset(["unit-023"])

        scores = score_risk_severity(dataset_version="unit")

        # f1 (a binary-classification figure) and severity_calibration_score
        # (a partial-credit figure) are independent fields - one is 1.0
        # (a correct risky-vs-not call) while the other is 0.5 (an
        # off-by-one severity), proving neither is blended into the other.
        assert scores.f1 == pytest.approx(1.0)
        assert scores.severity_calibration_score == pytest.approx(0.5)
        assert scores.f1 != scores.severity_calibration_score
