"""Tests for pipeline.services.extract_terms.

Spec: specs/pipeline/term-extraction/spec.md. Every
`core.llm_client.get_structured_completion` call is mocked - no real
network call is made.
"""

from unittest.mock import patch

import pytest
from django.conf import settings

from contracts.tests.factories import ClauseFactory
from pipeline.models import AuditLogEntry, ExtractedTerm
from pipeline.services import extract_terms

pytestmark = pytest.mark.django_db

PAYMENT_CLAUSE_TEXT = (
    "4. Payment Schedule. Vendor shall invoice Client monthly, and payment "
    "is due net 30 days from the invoice date."
)


def _extraction_response(*terms: dict) -> dict:
    return {"terms": list(terms)}


def _term(
    *,
    term_type="payout_frequency",
    value_raw="net 30 days from the invoice date",
    numeric_value=30,
    unit="days",
    is_formula_based=False,
    confidence=0.9,
):
    return {
        "term_type": term_type,
        "value_raw": value_raw,
        "numeric_value": numeric_value,
        "unit": unit,
        "is_formula_based": is_formula_based,
        "confidence": confidence,
    }


class TestExtractionScopedToPaymentBearingClauseTypes:
    """Requirement: Extraction scoped to payment-bearing clause types."""

    @pytest.mark.parametrize(
        "clause_type", ["termination", "dispute_resolution", "indemnity", "other"]
    )
    @patch("core.llm_client.get_structured_completion")
    def test_non_payment_clause_skips_extraction(self, mock_completion, clause_type):
        # Scenario: Non-payment clause skips extraction
        clause = ClauseFactory(clause_type=clause_type, clause_text="Boilerplate clause text.")

        result = extract_terms(clause=clause)

        assert result == []
        assert ExtractedTerm.objects.filter(clause=clause).count() == 0
        mock_completion.assert_not_called()
        assert AuditLogEntry.objects.filter(contract=clause.contract, stage=3).count() == 0

    @pytest.mark.parametrize(
        "clause_type", ["payment_schedule", "penalty_late_fee", "auto_renewal"]
    )
    @patch("core.llm_client.get_structured_completion")
    def test_payment_bearing_clause_types_run_extraction(self, mock_completion, clause_type):
        clause = ClauseFactory(clause_type=clause_type, clause_text=PAYMENT_CLAUSE_TEXT)
        mock_completion.return_value = _extraction_response(_term())

        result = extract_terms(clause=clause)

        assert len(result) == 1
        mock_completion.assert_called_once()


class TestOnlyStatedValuesAreExtracted:
    """Requirement: Only stated values are extracted."""

    @patch("core.llm_client.get_structured_completion")
    def test_qualitative_term_leaves_numeric_fields_unset(self, mock_completion):
        # Scenario: Qualitative term leaves numeric fields unset
        clause_text = (
            "5. Payment Schedule. Vendor shall be paid within a reasonable "
            "time after each milestone is accepted."
        )
        clause = ClauseFactory(clause_type="payment_schedule", clause_text=clause_text)
        mock_completion.return_value = _extraction_response(
            _term(
                term_type="milestone_trigger",
                value_raw="paid within a reasonable time after each milestone is accepted",
                numeric_value=None,
                unit=None,
                confidence=0.8,
            )
        )

        result = extract_terms(clause=clause)

        assert len(result) == 1
        term = result[0]
        assert term.value_structured["numeric_value"] is None
        assert term.value_structured["unit"] is None
        assert term.needs_human_review is False


class TestLowConfidenceOrUnparseableExtractionEscalated:
    """Requirement: Low-confidence or unparseable extraction escalated."""

    @patch("core.llm_client.get_structured_completion")
    def test_formula_based_term_flagged_and_raw_text_preserved(self, mock_completion):
        # Scenario: Formula-based term flagged
        clause_text = (
            "6. Penalty. Late payments accrue interest at 1.5% per month, "
            "compounding monthly on the outstanding balance."
        )
        clause = ClauseFactory(clause_type="penalty_late_fee", clause_text=clause_text)
        formula_quote = (
            "accrue interest at 1.5% per month, compounding monthly on the "
            "outstanding balance"
        )
        mock_completion.return_value = _extraction_response(
            _term(
                term_type="penalty_amount",
                value_raw=formula_quote,
                numeric_value=1.5,  # model attempts a number anyway
                unit="percent",
                is_formula_based=True,
                confidence=0.9,
            )
        )

        result = extract_terms(clause=clause)

        assert len(result) == 1
        term = result[0]
        assert term.needs_human_review is True
        assert term.value_raw == formula_quote
        assert term.value_structured["numeric_value"] is None

    @patch("core.llm_client.get_structured_completion")
    def test_confidence_below_threshold_escalates(self, mock_completion):
        clause = ClauseFactory(clause_type="payment_schedule", clause_text=PAYMENT_CLAUSE_TEXT)
        below_threshold = settings.EXTRACTION_MIN_CONFIDENCE - 0.1
        mock_completion.return_value = _extraction_response(
            _term(confidence=below_threshold)
        )

        result = extract_terms(clause=clause)

        assert result[0].needs_human_review is True

    @patch("core.llm_client.get_structured_completion")
    def test_non_grounded_value_raw_escalates(self, mock_completion):
        """A `value_raw` that is not actually verbatim in the clause must escalate."""
        clause = ClauseFactory(clause_type="payment_schedule", clause_text=PAYMENT_CLAUSE_TEXT)
        mock_completion.return_value = _extraction_response(
            _term(value_raw="a paraphrase not found in the clause text", confidence=0.95)
        )

        result = extract_terms(clause=clause)

        assert result[0].needs_human_review is True


class TestExtractedTermTraceableToItsClause:
    """Requirement: Extracted term traceable to its clause."""

    @patch("core.llm_client.get_structured_completion")
    def test_term_evidence_retrievable(self, mock_completion):
        # Scenario: Term evidence retrievable
        clause = ClauseFactory(clause_type="payment_schedule", clause_text=PAYMENT_CLAUSE_TEXT)
        mock_completion.return_value = _extraction_response(_term())

        extract_terms(clause=clause)

        stored = ExtractedTerm.objects.get(clause=clause)
        assert stored.clause_id == clause.id
        assert stored.value_raw in clause.clause_text


class TestExtractionAuditLogEntry:
    """One AuditLogEntry (stage=3) per extract_terms call."""

    @patch("core.llm_client.get_structured_completion")
    def test_one_audit_log_entry_created_per_call(self, mock_completion):
        clause = ClauseFactory(clause_type="payment_schedule", clause_text=PAYMENT_CLAUSE_TEXT)
        response = _extraction_response(_term())
        mock_completion.return_value = response

        extract_terms(clause=clause)

        entries = AuditLogEntry.objects.filter(contract=clause.contract, stage=3)
        assert entries.count() == 1
        entry = entries.get()
        assert entry.clause_id == clause.id
        assert entry.prompt_version == "term-extraction-v1"
        assert entry.llm_response_raw == response
