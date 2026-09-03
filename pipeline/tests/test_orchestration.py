"""Tests for pipeline.services.run_pipeline.

`run_pipeline` orchestrates the three stage functions, handing data between
them only via the database. Every `core.llm_client.get_structured_completion`
call is mocked - no real network call is made.

`razorpay_integration.services.detect_mismatches` (pipeline stage 4, added
in add-razorpay-crosscheck) is mocked too where a full run reaches it -
`run_pipeline` now calls it unconditionally after stage 3 (see
pipeline/services.py). This module tests stages 1-3 only; stage 4's own
behavior is covered by razorpay_integration/tests/.
"""

from unittest.mock import patch

import pytest

from contracts.models import Clause, Contract
from contracts.tests.factories import ContractFactory
from pipeline.models import AuditLogEntry, ExtractedTerm
from pipeline.services import run_pipeline

pytestmark = pytest.mark.django_db

PAYMENT_CLAUSE_TEXT = (
    "1. Payment Schedule. Vendor shall invoice Client monthly, and payment "
    "is due net 30 days from the invoice date."
)

_SEGMENTATION_RESPONSE = {"clauses": [{"text": PAYMENT_CLAUSE_TEXT}]}
_CLASSIFICATION_RESPONSE = {
    "primary_label": "payment_schedule",
    "primary_confidence": 0.9,
    "secondary_label": "termination",
    "secondary_confidence": 0.1,
    "rationale": "States a monthly invoicing schedule and a 30-day payment term.",
}
_EXTRACTION_RESPONSE = {
    "terms": [
        {
            "term_type": "payout_frequency",
            "value_raw": "net 30 days from the invoice date",
            "numeric_value": 30,
            "unit": "days",
            "is_formula_based": False,
            "confidence": 0.9,
        }
    ]
}


class TestRunPipelineFullRun:
    @patch("risk_scoring.services.score_clause")
    @patch("razorpay_integration.services.detect_mismatches")
    @patch("core.llm_client.get_structured_completion")
    def test_full_run_produces_clause_extracted_term_and_audit_rows(
        self, mock_completion, mock_detect_mismatches, mock_score_clause
    ):
        contract = ContractFactory(raw_text=PAYMENT_CLAUSE_TEXT)
        mock_completion.side_effect = [
            _SEGMENTATION_RESPONSE,
            _CLASSIFICATION_RESPONSE,
            _EXTRACTION_RESPONSE,
        ]

        run_pipeline(contract=contract, from_stage=1)

        assert mock_completion.call_count == 3

        clauses = list(Clause.objects.filter(contract=contract))
        assert len(clauses) == 1
        clause = clauses[0]
        assert clause.clause_type == "payment_schedule"

        terms = list(ExtractedTerm.objects.filter(clause=clause))
        assert len(terms) == 1
        assert terms[0].term_type == "payout_frequency"

        audit_stages = sorted(
            AuditLogEntry.objects.filter(contract=contract).values_list("stage", flat=True)
        )
        assert audit_stages == [1, 2, 3]

        reloaded_contract = Contract.objects.get(id=contract.id)
        assert reloaded_contract.needs_human_review is False

    @patch("core.llm_client.get_structured_completion")
    def test_run_pipeline_rejects_invalid_from_stage(self, mock_completion):
        contract = ContractFactory(raw_text=PAYMENT_CLAUSE_TEXT)

        with pytest.raises(ValueError):
            run_pipeline(contract=contract, from_stage=4)

        mock_completion.assert_not_called()

    @patch("razorpay_integration.services.detect_mismatches")
    @patch("core.llm_client.get_structured_completion")
    def test_segmentation_failure_leaves_no_clauses_and_does_not_run_later_stages(
        self, mock_completion, mock_detect_mismatches
    ):
        contract = ContractFactory(raw_text=PAYMENT_CLAUSE_TEXT)
        non_verbatim_response = {
            "clauses": [{"text": "This text is not present in the source at all."}]
        }
        mock_completion.side_effect = [non_verbatim_response, non_verbatim_response]

        run_pipeline(contract=contract, from_stage=1)

        # Only the two segmentation attempts happen - stage 2/3 loops iterate
        # over zero clauses (nothing was persisted), so no further calls.
        assert mock_completion.call_count == 2
        assert Clause.objects.filter(contract=contract).count() == 0
        reloaded_contract = Contract.objects.get(id=contract.id)
        assert reloaded_contract.needs_human_review is True
