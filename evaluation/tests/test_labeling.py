"""Tests for `evaluation.services.label_synthetic_contract` (tasks 2.5, 2.6)."""

from unittest.mock import patch

import pytest

from evaluation.dataset_types import SyntheticContractParams
from evaluation.models import EvalLabel, EvalLabelType
from evaluation.services import generate_synthetic_contract, label_synthetic_contract

pytestmark = pytest.mark.django_db

_PARAMS = SyntheticContractParams(
    engagement_type="retainer",
    domain="consulting",
    clause_severity_profile="mildly-one-sided",
    phrasing_style="legalese",
    razorpay_reference_type="payout",
    seed=99,
)


def _phrasing_response(count: int = 5) -> dict:
    return {"clauses": [{"text": f"Generic clause prose number {i}."} for i in range(count)]}


@pytest.fixture
def synthetic_contract():
    with patch("core.llm_client.get_structured_completion", return_value=_phrasing_response()):
        return generate_synthetic_contract(params=_PARAMS, dataset_version="v1", sequence_number=1)


class TestLabelCompleteness:
    """Requirement: Label completeness (task 2.5)."""

    def test_every_clause_label_carries_all_five_rubric_fields(self, synthetic_contract):
        labels = label_synthetic_contract(contract=synthetic_contract, params=_PARAMS)

        clause_labels = [label for label in labels if label.clause_id is not None]
        assert len(clause_labels) == 5
        for label in clause_labels:
            gt = label.ground_truth_value
            assert gt["clause_type"]
            assert isinstance(gt["risky"], bool)
            assert 1 <= gt["severity"] <= 5
            assert gt["rationale"]
            assert isinstance(gt["needs_human_review"], bool)
            assert label.label_type == EvalLabelType.RISK_SEVERITY
            assert label.annotator == "synthetic-rubric-v1"

    def test_labels_are_persisted(self, synthetic_contract):
        label_synthetic_contract(contract=synthetic_contract, params=_PARAMS)

        # 5 clause-level labels + 1 contract-level (overall_risk_tier) label.
        assert EvalLabel.objects.filter(contract=synthetic_contract).count() == 6


class TestContractLevelFloorRuleLabel:
    """Requirement: Per-contract risk tier with a floor rule (task 2.6)."""

    def test_a_contract_level_label_with_overall_risk_tier_is_created(self, synthetic_contract):
        labels = label_synthetic_contract(contract=synthetic_contract, params=_PARAMS)

        contract_level = [label for label in labels if label.clause_id is None]
        assert len(contract_level) == 1
        assert "overall_risk_tier" in contract_level[0].ground_truth_value

    def test_floor_rule_forces_critical_when_two_clauses_score_four_or_higher(
        self, synthetic_contract
    ):
        # Directly construct EvalLabel rows the way label_synthetic_contract
        # would, forcing exactly the floor-rule scenario: two severity-4
        # clauses, no severity-5 clause.
        from evaluation.services import compute_overall_risk_tier

        assert compute_overall_risk_tier(clause_severities=[4, 4, 2, 1, 1]) == "critical"
