"""Tests for the `run_pipeline` management command.

`razorpay_integration.services.detect_mismatches` (pipeline stage 4, added
in add-razorpay-crosscheck) and `risk_scoring.services.score_clause`
(pipeline stage 5, added in add-risk-scoring-report) are mocked in the
full-run tests below, the same way `core.llm_client.get_structured_completion`
is - `run_pipeline` now calls both unconditionally after stage 3 (see
pipeline/services.py), and this module tests stages 1-3 only; stage 4's and
stage 5's own behavior are covered by razorpay_integration/tests/ and
risk_scoring/tests/ respectively.
"""

import uuid
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from contracts.models import Clause
from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.models import AuditLogEntry, ExtractedTerm

pytestmark = pytest.mark.django_db

PAYMENT_CLAUSE_TEXT = (
    "1. Payment Schedule. Vendor shall invoice Client monthly, and payment "
    "is due net 30 days from the invoice date."
)
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


@patch("risk_scoring.services.score_clause")
@patch("razorpay_integration.services.detect_mismatches")
@patch("core.llm_client.get_structured_completion")
def test_resumes_correctly_from_stage_2_on_a_contract_with_existing_clauses(
    mock_completion, mock_detect_mismatches, mock_score_clause
):
    contract = ContractFactory(raw_text=PAYMENT_CLAUSE_TEXT)
    # Simulate stage 1 having already run in a prior invocation.
    existing_clause = ClauseFactory(
        contract=contract, sequence_index=0, clause_text=PAYMENT_CLAUSE_TEXT
    )
    mock_completion.side_effect = [_CLASSIFICATION_RESPONSE, _EXTRACTION_RESPONSE]

    call_command(
        "run_pipeline",
        f"--contract-id={contract.id}",
        "--from-stage=2",
    )

    # Exactly the classification and extraction calls - no segmentation call.
    assert mock_completion.call_count == 2
    assert Clause.objects.filter(contract=contract).count() == 1

    reloaded_clause = Clause.objects.get(id=existing_clause.id)
    assert reloaded_clause.clause_type == "payment_schedule"
    assert ExtractedTerm.objects.filter(clause=reloaded_clause).count() == 1

    assert AuditLogEntry.objects.filter(contract=contract, stage=1).count() == 0
    assert AuditLogEntry.objects.filter(contract=contract, stage=2).count() == 1
    assert AuditLogEntry.objects.filter(contract=contract, stage=3).count() == 1


@patch("risk_scoring.services.score_clause")
@patch("razorpay_integration.services.detect_mismatches")
@patch("core.llm_client.get_structured_completion")
def test_defaults_to_a_full_run_from_stage_1(
    mock_completion, mock_detect_mismatches, mock_score_clause
):
    contract = ContractFactory(raw_text=PAYMENT_CLAUSE_TEXT)
    mock_completion.side_effect = [
        {"clauses": [{"text": PAYMENT_CLAUSE_TEXT}]},
        _CLASSIFICATION_RESPONSE,
        _EXTRACTION_RESPONSE,
    ]

    call_command("run_pipeline", f"--contract-id={contract.id}")

    assert mock_completion.call_count == 3
    assert Clause.objects.filter(contract=contract).count() == 1


def test_unknown_contract_id_raises_command_error():
    with pytest.raises(CommandError):
        call_command("run_pipeline", f"--contract-id={uuid.uuid4()}")


def test_invalid_contract_id_raises_command_error():
    with pytest.raises(CommandError):
        call_command("run_pipeline", "--contract-id=not-a-uuid")


def test_invalid_from_stage_raises_command_error():
    contract = ContractFactory(raw_text=PAYMENT_CLAUSE_TEXT)

    with pytest.raises(CommandError):
        call_command("run_pipeline", f"--contract-id={contract.id}", "--from-stage=7")
