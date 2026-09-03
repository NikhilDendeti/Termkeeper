"""Tests for `evaluation.selectors.score_mismatch_flags` (task 6.1)."""

import pytest

from contracts.tests.factories import ClauseFactory, ContractFactory
from evaluation.selectors import score_mismatch_flags
from evaluation.tests.factories import EvalLabelFactory
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.models import MismatchType
from razorpay_integration.tests.factories import MismatchFlagFactory

pytestmark = pytest.mark.django_db

_DATASET_VERSION = "unit-mismatch"
_PREFIX = f"synthetic-{_DATASET_VERSION}-fixture-"


def _mismatch_labeled_clause(*, scenario_id, expected_mismatch_type):
    contract = ContractFactory(engagement_id=f"{_PREFIX}{scenario_id}")
    clause = ClauseFactory(contract=contract)
    EvalLabelFactory(
        contract=contract,
        clause=clause,
        label_type="mismatch_present",
        ground_truth_value={
            "mismatch_type": expected_mismatch_type,
            "expected_verdict": expected_mismatch_type or "no_mismatch",
        },
    )
    return contract, clause


class TestMatchRequiresBothClauseIdAndMismatchType:
    """Requirement: Match requires both clause id and mismatch_type (task 6.1)."""

    def test_a_flag_with_the_right_clause_but_wrong_type_is_not_a_true_positive(self):
        _, clause = _mismatch_labeled_clause(
            scenario_id="01", expected_mismatch_type=MismatchType.CADENCE_MISMATCH.value
        )
        term = ExtractedTermFactory(clause=clause)
        # Predicted flag on the SAME clause, but a DIFFERENT mismatch_type.
        MismatchFlagFactory(extracted_term=term, mismatch_type=MismatchType.AMOUNT_MISMATCH.value)

        scores = score_mismatch_flags(dataset_version=_DATASET_VERSION)

        assert scores.true_positives == 0
        assert scores.false_positives == 1
        assert scores.false_negatives == 1

    def test_matching_clause_and_mismatch_type_is_a_true_positive(self):
        _, clause = _mismatch_labeled_clause(
            scenario_id="02", expected_mismatch_type=MismatchType.CADENCE_MISMATCH.value
        )
        term = ExtractedTermFactory(clause=clause)
        MismatchFlagFactory(extracted_term=term, mismatch_type=MismatchType.CADENCE_MISMATCH.value)

        scores = score_mismatch_flags(dataset_version=_DATASET_VERSION)

        assert scores.true_positives == 1
        assert scores.false_positives == 0
        assert scores.false_negatives == 0
        assert scores.precision == pytest.approx(1.0)
        assert scores.recall == pytest.approx(1.0)

    def test_expected_no_mismatch_with_no_predicted_flag_contributes_nothing(self):
        _mismatch_labeled_clause(scenario_id="03", expected_mismatch_type=None)

        scores = score_mismatch_flags(dataset_version=_DATASET_VERSION)

        assert scores.true_positives == 0
        assert scores.false_positives == 0
        assert scores.false_negatives == 0

    def test_scoring_is_scoped_to_this_dataset_versions_fixture_contracts_only(self):
        # A mismatch_present label under a DIFFERENT dataset_version's
        # fixture-contract namespace must not leak into this dataset
        # version's score.
        other_contract = ContractFactory(engagement_id="synthetic-other-fixture-99")
        other_clause = ClauseFactory(contract=other_contract)
        EvalLabelFactory(
            contract=other_contract,
            clause=other_clause,
            label_type="mismatch_present",
            ground_truth_value={"mismatch_type": MismatchType.CADENCE_MISMATCH.value},
        )

        scores = score_mismatch_flags(dataset_version=_DATASET_VERSION)

        assert scores.true_positives == 0
        assert scores.false_positives == 0
        assert scores.false_negatives == 0
