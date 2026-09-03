"""Tests for stage-5 wiring into pipeline.services.run_pipeline (task 5.1).

See design.md (add-risk-scoring-report) - "Extending run_pipeline without a
new circular import."
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from contracts.models import Clause
from contracts.tests.factories import ContractFactory
from pipeline.models import AuditLogEntry
from pipeline.services import run_pipeline
from risk_scoring.models import RiskAssessment

pytestmark = pytest.mark.django_db

PAYMENT_CLAUSE_TEXT = (
    "1. Payment Schedule. Vendor shall invoice Client monthly, and payment "
    "is due net 30 days from the invoice date."
)
TERMINATION_CLAUSE_TEXT = (
    "2. Termination. Either party may terminate this Agreement upon 90 days "
    "written notice; Vendor may also terminate immediately for cause."
)

_SEGMENTATION_RESPONSE = {
    "clauses": [{"text": PAYMENT_CLAUSE_TEXT}, {"text": TERMINATION_CLAUSE_TEXT}]
}
_PAYMENT_CLASSIFICATION_RESPONSE = {
    "primary_label": "payment_schedule",
    "primary_confidence": 0.9,
    "secondary_label": "termination",
    "secondary_confidence": 0.1,
    "rationale": "States a monthly invoicing schedule and a 30-day payment term.",
}
_TERMINATION_CLASSIFICATION_RESPONSE = {
    "primary_label": "termination",
    "primary_confidence": 0.9,
    "secondary_label": "dispute_resolution",
    "secondary_confidence": 0.1,
    "rationale": "States termination notice terms.",
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
_PAYMENT_RISK_SCORING_RESPONSE = {
    "sentences": [
        {
            "text": "Payment is due a fixed 30 days after invoicing.",
            "quote": "net 30 days from the invoice date",
        }
    ],
    "asymmetry_score": 0.3,
    "suggested_rewrite": None,
}
_TERMINATION_RISK_SCORING_RESPONSE = {
    "sentences": [
        {
            "text": "Vendor may terminate immediately for cause with no notice period.",
            "quote": "Vendor may also terminate immediately for cause",
        }
    ],
    "asymmetry_score": 0.5,
    "suggested_rewrite": "Require symmetric notice periods for both parties.",
}


class TestStage5ScoresEveryClauseAfterAFullPipelineRun:
    @patch("razorpay_integration.services.detect_mismatches")
    @patch("core.llm_client.get_structured_completion")
    def test_termination_clause_with_no_extracted_terms_still_gets_scored(
        self, mock_completion, mock_detect_mismatches
    ):
        contract = ContractFactory(
            raw_text=PAYMENT_CLAUSE_TEXT + " " + TERMINATION_CLAUSE_TEXT
        )
        # extract_terms no-ops (no Claude call) for the non-payment-bearing
        # termination clause, so only one extraction response is needed.
        mock_completion.side_effect = [
            _SEGMENTATION_RESPONSE,
            _PAYMENT_CLASSIFICATION_RESPONSE,
            _TERMINATION_CLASSIFICATION_RESPONSE,
            _EXTRACTION_RESPONSE,
            _PAYMENT_RISK_SCORING_RESPONSE,
            _TERMINATION_RISK_SCORING_RESPONSE,
        ]

        run_pipeline(contract=contract, from_stage=1)

        assert mock_completion.call_count == 6

        termination_clause = Clause.objects.get(contract=contract, clause_type="termination")
        assert not termination_clause.extracted_terms.exists()

        assessments = RiskAssessment.objects.filter(clause__contract=contract)
        assert assessments.count() == 2

        termination_assessment = RiskAssessment.objects.get(clause=termination_clause)
        assert termination_assessment.severity != "needs_human_review"
        assert AuditLogEntry.objects.filter(contract=contract, stage=5).count() == 2
