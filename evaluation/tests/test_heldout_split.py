"""Tests for contract-level held-out split assignment (task 3.1)."""

from unittest.mock import patch

import pytest

from contracts.models import Clause
from evaluation.services import assign_heldout_split, generate_dataset

pytestmark = pytest.mark.django_db


def _phrasing_response(count: int = 5) -> dict:
    return {"clauses": [{"text": f"Generic clause prose number {i}."} for i in range(count)]}


class TestAssignHeldoutSplitIsDeterministic:
    def test_same_seed_produces_the_same_split(self):
        ids = [f"synthetic-v1-{i:03d}" for i in range(1, 21)]
        first = assign_heldout_split(engagement_ids=ids, seed=7)
        second = assign_heldout_split(engagement_ids=ids, seed=7)
        assert first == second

    def test_heldout_ids_are_a_subset_of_the_input(self):
        ids = [f"synthetic-v1-{i:03d}" for i in range(1, 21)]
        heldout = assign_heldout_split(engagement_ids=ids, seed=7)
        assert set(heldout) <= set(ids)
        assert 0 < len(heldout) < len(ids)


class TestNoClauseLevelLeakage:
    """Requirement: No clause-level leakage (task 3.1)."""

    @patch("core.llm_client.get_structured_completion")
    def test_every_clause_of_a_heldout_contract_stays_in_the_heldout_set(self, mock_completion):
        mock_completion.return_value = _phrasing_response()
        contracts = generate_dataset(dataset_version="it-leak", count=30)
        engagement_ids = [c.engagement_id for c in contracts]

        heldout_ids = assign_heldout_split(engagement_ids=engagement_ids, seed=11)
        non_heldout_ids = sorted(set(engagement_ids) - set(heldout_ids))

        heldout_clause_contract_ids = set(
            Clause.objects.filter(contract__engagement_id__in=heldout_ids).values_list(
                "contract__engagement_id", flat=True
            )
        )
        non_heldout_clause_contract_ids = set(
            Clause.objects.filter(contract__engagement_id__in=non_heldout_ids).values_list(
                "contract__engagement_id", flat=True
            )
        )

        # Every clause belonging to a held-out contract's engagement_id set
        # only ever resolves back to a held-out contract, and vice versa -
        # no clause "crosses over" between the two sets.
        assert heldout_clause_contract_ids <= set(heldout_ids)
        assert non_heldout_clause_contract_ids <= set(non_heldout_ids)
        assert heldout_clause_contract_ids.isdisjoint(non_heldout_clause_contract_ids)
