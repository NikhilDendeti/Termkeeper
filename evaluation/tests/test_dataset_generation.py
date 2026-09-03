"""Tests for full dataset generation (task 2.4)."""

from unittest.mock import patch

import pytest

from contracts.models import Contract
from evaluation.dataset_types import (
    ClauseSeverityProfile,
    Domain,
    EngagementType,
    PhrasingStyle,
)
from evaluation.services import DEFAULT_DATASET_SIZE, build_dataset_params, generate_dataset

pytestmark = pytest.mark.django_db


def _phrasing_response(count: int = 5) -> dict:
    return {"clauses": [{"text": f"Generic clause prose number {i}."} for i in range(count)]}


class TestDatasetSizeBounds:
    """Requirement: Dataset size bounds (task 2.4)."""

    def test_default_dataset_size_is_within_bounds(self):
        assert 30 <= DEFAULT_DATASET_SIZE <= 50

    def test_build_dataset_params_rejects_out_of_bounds_count(self):
        with pytest.raises(ValueError):
            build_dataset_params(count=10)
        with pytest.raises(ValueError):
            build_dataset_params(count=60)


class TestFullAxisCoverage:
    """Requirement: Full axis coverage across the dataset (task 2.4)."""

    def test_every_axis_value_appears_at_least_once(self):
        params_list = build_dataset_params(count=DEFAULT_DATASET_SIZE)

        engagement_types = {p.engagement_type for p in params_list}
        domains = {p.domain for p in params_list}
        severity_profiles = {p.clause_severity_profile for p in params_list}
        phrasing_styles = {p.phrasing_style for p in params_list}
        reference_types = {p.razorpay_reference_type for p in params_list}

        assert engagement_types == {choice.value for choice in EngagementType}
        assert domains == {choice.value for choice in Domain}
        assert severity_profiles == {choice.value for choice in ClauseSeverityProfile}
        assert phrasing_styles == {choice.value for choice in PhrasingStyle}
        assert reference_types == {"payout", "subscription"}


class TestGenerateDataset:
    @patch("core.llm_client.get_structured_completion")
    def test_generates_and_labels_every_contract(self, mock_completion):
        mock_completion.return_value = _phrasing_response()

        contracts = generate_dataset(dataset_version="it-small", count=30)

        assert len(contracts) == 30
        persisted = Contract.objects.filter(engagement_id__startswith="synthetic-it-small-")
        assert persisted.count() == 30
        for contract in contracts:
            assert contract.eval_labels.exists()
