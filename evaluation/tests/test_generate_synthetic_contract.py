"""Tests for `evaluation.services.generate_synthetic_contract` (task 2.2)."""

from unittest.mock import patch

import pytest

from contracts.models import Clause, Contract
from evaluation.dataset_types import SyntheticContractParams
from evaluation.services import (
    SyntheticGenerationError,
    generate_clause_ground_truth,
    generate_synthetic_contract,
)

pytestmark = pytest.mark.django_db

_PARAMS = SyntheticContractParams(
    engagement_type="milestone",
    domain="design",
    clause_severity_profile="deliberately-exploitative",
    phrasing_style="deliberately-vague",
    razorpay_reference_type="subscription",
    seed=777,
)


_PLACEHOLDER_WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]


def _phrasing_response(count: int) -> dict:
    # Deliberately generic, entirely non-numeric prose - proves the
    # persisted ground truth isn't merely "whatever happens to be parseable
    # from the text" but genuinely independent of it.
    words = [_PLACEHOLDER_WORDS[i % len(_PLACEHOLDER_WORDS)] for i in range(count)]
    return {"clauses": [{"text": f"Generic clause prose paragraph {word}."} for word in words]}


class TestGeneratesContractFromPhrasedProse:
    @patch("core.llm_client.get_structured_completion")
    def test_persists_a_contract_with_expected_metadata(self, mock_completion):
        mock_completion.return_value = _phrasing_response(5)

        contract = generate_synthetic_contract(
            params=_PARAMS, dataset_version="v1", sequence_number=4
        )

        assert Contract.objects.filter(id=contract.id).exists()
        assert contract.engagement_id == "synthetic-v1-004"
        assert contract.razorpay_reference_type == "subscription"
        assert Clause.objects.filter(contract=contract).count() == 5

    @patch("core.llm_client.get_structured_completion")
    def test_clause_rows_persisted_in_order(self, mock_completion):
        mock_completion.return_value = _phrasing_response(5)

        contract = generate_synthetic_contract(
            params=_PARAMS, dataset_version="v1", sequence_number=1
        )

        clauses = list(Clause.objects.filter(contract=contract).order_by("sequence_index"))
        assert [c.sequence_index for c in clauses] == [0, 1, 2, 3, 4]
        for clause in clauses:
            assert clause.clause_text in contract.raw_text

    @patch("core.llm_client.get_structured_completion")
    def test_mismatched_paragraph_count_raises(self, mock_completion):
        mock_completion.return_value = _phrasing_response(2)  # expected 5

        with pytest.raises(SyntheticGenerationError):
            generate_synthetic_contract(params=_PARAMS, dataset_version="v1", sequence_number=1)


class TestGroundTruthNeverParsedFromProse:
    """Requirement: Ground truth generated before prose (task 2.2)."""

    @patch("core.llm_client.get_structured_completion")
    def test_ground_truth_values_are_never_derivable_by_parsing_raw_text(self, mock_completion):
        mock_completion.return_value = _phrasing_response(5)

        contract = generate_synthetic_contract(
            params=_PARAMS, dataset_version="v1", sequence_number=2
        )
        ground_truths = generate_clause_ground_truth(params=_PARAMS)

        # None of the ground-truth numeric values appear anywhere in the
        # persisted raw_text - the mocked phrasing call returned generic,
        # entirely non-numeric placeholder prose, proving the ground truth
        # is carried independently of (never scraped back out of) the
        # generated text. Single-digit strings are excluded from the check:
        # raw_text's own "1. "/"2. "/... clause-ordinal numbering
        # legitimately contains digits 1-5, which would otherwise produce
        # spurious collisions unrelated to whether a *value* was parsed.
        numeric_strings = {
            str(value)
            for gt in ground_truths
            for value in (gt.amount, gt.cadence_days, gt.notice_period_days, gt.penalty_pct)
            if value is not None and len(str(value)) >= 2
        }
        assert numeric_strings, "expected at least one multi-digit ground-truth value to check"
        for numeric_string in numeric_strings:
            assert numeric_string not in contract.raw_text

    @patch("core.llm_client.get_structured_completion")
    def test_phrasing_call_receives_ground_truth_generated_before_it_is_called(
        self, mock_completion
    ):
        captured_user_content: list[str] = []

        def _capture(system_prompt, user_content, schema, *, prompt_version):
            captured_user_content.append(user_content)
            return _phrasing_response(5)

        mock_completion.side_effect = _capture

        generate_synthetic_contract(params=_PARAMS, dataset_version="v1", sequence_number=3)

        ground_truths = generate_clause_ground_truth(params=_PARAMS)
        # The ground truth fed into the (mocked) phrasing call's input
        # matches the pure, seeded generator's output - i.e. numeric values
        # exist prior to, and independently of, the phrasing call.
        assert captured_user_content
        for ground_truth in ground_truths:
            if ground_truth.amount is not None:
                assert str(ground_truth.amount) in captured_user_content[0]
