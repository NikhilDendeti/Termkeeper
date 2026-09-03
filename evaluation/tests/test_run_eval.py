"""Integration test for `evaluation.services.run_eval` (task 7.1).

Runs end to end against the real, committed `eval/v1` dataset - i.e. the
actual `evaluation/fixtures/eval/v1/heldout_manifest.json` this change ships
(no monkeypatching of the fixtures root) - by constructing Contract/Clause/
EvalLabel/RiskAssessment rows for exactly the held-out `engagement_id`s that
manifest lists, then calling `run_eval(dataset_version="v1")` for real.
"""

import pytest

from contracts.tests.factories import ClauseFactory, ContractFactory
from evaluation.selectors import get_heldout_manifest
from evaluation.services import FIXTURE_ENGAGEMENT_PREFIX_TEMPLATE, run_eval
from evaluation.tests.factories import EvalLabelFactory
from pipeline.tests.factories import AuditLogEntryFactory, ExtractedTermFactory
from razorpay_integration.models import MismatchType
from razorpay_integration.tests.factories import MismatchFlagFactory
from risk_scoring.models import SeverityChoices
from risk_scoring.tests.factories import RiskAssessmentFactory

pytestmark = pytest.mark.django_db

_DATASET_VERSION = "v1"


@pytest.fixture
def v1_heldout_dataset():
    manifest = get_heldout_manifest(dataset_version=_DATASET_VERSION)
    heldout_ids = manifest.heldout_engagement_ids
    assert heldout_ids, "the committed eval/v1 manifest must list at least one held-out contract"

    # One labeled+scored clause per held-out contract in the real manifest -
    # a mix of TP/TN so precision/recall/f1 are all meaningfully non-trivial.
    predictions = [
        (True, 5, SeverityChoices.CRITICAL),
        (False, 1, SeverityChoices.LOW),
        (True, 4, SeverityChoices.HIGH),
    ]
    for index, engagement_id in enumerate(heldout_ids):
        risky, severity, predicted_severity = predictions[index % len(predictions)]
        contract = ContractFactory(engagement_id=engagement_id)
        clause = ClauseFactory(contract=contract, clause_type="payment_schedule")
        EvalLabelFactory(
            contract=contract,
            clause=clause,
            ground_truth_value={
                "clause_type": "payment_schedule",
                "risky": risky,
                "severity": severity,
                "rationale": "test rationale naming a mechanism",
                "needs_human_review": False,
            },
        )
        RiskAssessmentFactory(clause=clause, severity=predicted_severity)
        AuditLogEntryFactory(contract=contract, stage=2, prompt_version="clause-classification-v1")

    # One fixture-matrix-style contract for mismatch_present scoring, using
    # the same engagement_id namespace `load_razorpay_fixture_scenarios`
    # would produce for this dataset_version.
    fixture_prefix = FIXTURE_ENGAGEMENT_PREFIX_TEMPLATE.format(dataset_version=_DATASET_VERSION)
    fixture_contract = ContractFactory(engagement_id=f"{fixture_prefix}cadence_mismatch_01")
    fixture_clause = ClauseFactory(contract=fixture_contract, clause_type="payment_schedule")
    EvalLabelFactory(
        contract=fixture_contract,
        clause=fixture_clause,
        label_type="mismatch_present",
        ground_truth_value={"mismatch_type": MismatchType.CADENCE_MISMATCH.value},
    )
    term = ExtractedTermFactory(clause=fixture_clause)
    MismatchFlagFactory(extracted_term=term, mismatch_type=MismatchType.CADENCE_MISMATCH.value)

    return heldout_ids, predictions


class TestRunEvalEndToEnd:
    """Task 7.1: run_eval composes manifest check + scoring into one persisted EvalRun."""

    def test_every_eval_run_field_is_populated(self, v1_heldout_dataset):
        heldout_ids, predictions = v1_heldout_dataset

        eval_run = run_eval(dataset_version=_DATASET_VERSION, fixture_version="v1")

        assert eval_run.dataset_version == _DATASET_VERSION
        assert eval_run.fixture_version == "v1"

        assert "risk_severity" in eval_run.precision_recall_f1
        assert "mismatch_present" in eval_run.precision_recall_f1
        risk_severity = eval_run.precision_recall_f1["risk_severity"]
        expected_tp = sum(
            1
            for index in range(len(heldout_ids))
            if predictions[index % len(predictions)][0]  # risky
        )
        expected_tn = len(heldout_ids) - expected_tp
        assert risk_severity["true_positives"] == expected_tp
        assert risk_severity["true_negatives"] == expected_tn
        assert risk_severity["scored_clause_count"] == len(heldout_ids)

        mismatch_present = eval_run.precision_recall_f1["mismatch_present"]
        assert mismatch_present["true_positives"] == 1

        assert 0.0 <= eval_run.severity_calibration_score <= 1.0
        assert eval_run.cost_report
        assert eval_run.false_positive_cost_note
        assert "5.0" in eval_run.false_positive_cost_note
        assert eval_run.pipeline_version
        assert eval_run.prompt_version == "clause-classification-v1"
