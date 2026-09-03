"""Tests for `evaluation.selectors.compute_cost_report` (task 6.2)."""

import pytest

from contracts.tests.factories import ClauseFactory, ContractFactory
from evaluation.selectors import compute_cost_report
from evaluation.tests.factories import EvalLabelFactory
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.models import MismatchType
from razorpay_integration.tests.factories import MismatchFlagFactory

pytestmark = pytest.mark.django_db

_DATASET_VERSION = "unit-cost"
_PREFIX = f"synthetic-{_DATASET_VERSION}-fixture-"


def _labeled_clause(*, scenario_id, expected_mismatch_type, clause_type="payment_schedule"):
    contract = ContractFactory(engagement_id=f"{_PREFIX}{scenario_id}")
    clause = ClauseFactory(contract=contract, clause_type=clause_type)
    EvalLabelFactory(
        contract=contract,
        clause=clause,
        label_type="mismatch_present",
        ground_truth_value={"mismatch_type": expected_mismatch_type},
    )
    return contract, clause


class TestCostsBrokenDownNeverBlended:
    """Requirement: Costs broken down, never blended (task 6.2)."""

    def test_breakdown_by_clause_type_and_mismatch_type_is_present(self):
        _, fp_clause = _labeled_clause(scenario_id="01", expected_mismatch_type=None)
        term = ExtractedTermFactory(clause=fp_clause)
        MismatchFlagFactory(extracted_term=term, mismatch_type=MismatchType.CADENCE_MISMATCH.value)

        _, fn_clause = _labeled_clause(
            scenario_id="02", expected_mismatch_type=MismatchType.AMOUNT_MISMATCH.value
        )

        report = compute_cost_report(
            dataset_version=_DATASET_VERSION, minutes_per_dismissed_flag=5.0
        )

        assert report.fp_count == 1
        assert report.fn_count == 1
        assert report.fp_cost == pytest.approx(5.0)
        assert report.fn_cost > 0.0
        assert "payment_schedule" in report.by_clause_type
        assert MismatchType.CADENCE_MISMATCH.value in report.by_mismatch_type
        assert MismatchType.AMOUNT_MISMATCH.value in report.by_mismatch_type

    def test_no_single_blended_cost_number_replaces_the_breakdown(self):
        _, fp_clause = _labeled_clause(scenario_id="03", expected_mismatch_type=None)
        term = ExtractedTermFactory(clause=fp_clause)
        MismatchFlagFactory(extracted_term=term, mismatch_type=MismatchType.CADENCE_MISMATCH.value)

        report = compute_cost_report(
            dataset_version=_DATASET_VERSION, minutes_per_dismissed_flag=5.0
        )
        as_dict = report.as_dict()

        # fp_cost and fn_cost are always reported *alongside* the by_-
        # breakdown dicts, never in place of them.
        assert "by_clause_type" in as_dict
        assert "by_mismatch_type" in as_dict
        assert isinstance(as_dict["by_clause_type"], dict)
        assert isinstance(as_dict["by_mismatch_type"], dict)
        assert "fp_cost" in as_dict and "fn_cost" in as_dict

    def test_ratio_is_none_when_there_are_no_false_positives(self):
        _, fn_clause = _labeled_clause(
            scenario_id="04", expected_mismatch_type=MismatchType.AMOUNT_MISMATCH.value
        )

        report = compute_cost_report(
            dataset_version=_DATASET_VERSION, minutes_per_dismissed_flag=5.0
        )

        assert report.fp_count == 0
        assert report.fn_to_fp_cost_ratio is None

    def test_minutes_per_dismissed_flag_assumption_is_a_named_parameter(self):
        _, fp_clause = _labeled_clause(scenario_id="05", expected_mismatch_type=None)
        term = ExtractedTermFactory(clause=fp_clause)
        MismatchFlagFactory(extracted_term=term, mismatch_type=MismatchType.CADENCE_MISMATCH.value)

        report_cheap = compute_cost_report(
            dataset_version=_DATASET_VERSION, minutes_per_dismissed_flag=1.0
        )
        report_expensive = compute_cost_report(
            dataset_version=_DATASET_VERSION, minutes_per_dismissed_flag=10.0
        )

        assert report_cheap.fp_cost == pytest.approx(1.0)
        assert report_expensive.fp_cost == pytest.approx(10.0)
