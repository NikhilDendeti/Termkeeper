"""Tests for pipeline.services.classify_clause.

Spec: specs/pipeline/clause-classification/spec.md. Every
`core.llm_client.get_structured_completion` call is mocked - no real
network call is made.
"""

from unittest.mock import patch

import pytest
from django.conf import settings

from contracts.models import Clause, ClauseType
from contracts.tests.factories import ClauseFactory
from pipeline.models import AuditLogEntry
from pipeline.services import classify_clause

pytestmark = pytest.mark.django_db


def _classification_response(
    *,
    primary_label="payment_schedule",
    primary_confidence=0.9,
    secondary_label="termination",
    secondary_confidence=0.2,
    rationale="States a monthly invoicing schedule and a 30-day payment term.",
):
    return {
        "primary_label": primary_label,
        "primary_confidence": primary_confidence,
        "secondary_label": secondary_label,
        "secondary_confidence": secondary_confidence,
        "rationale": rationale,
    }


class TestFixedClauseTypeTaxonomy:
    """Requirement: Fixed clause-type taxonomy."""

    @patch("core.llm_client.get_structured_completion")
    def test_classification_restricted_to_the_taxonomy(self, mock_completion):
        # Scenario: Classification restricted to the taxonomy
        clause = ClauseFactory(clause_text="Payment is due net 30 days from the invoice date.")
        mock_completion.return_value = _classification_response(primary_label="payment_schedule")

        result = classify_clause(clause=clause)

        valid_labels = {choice.value for choice in ClauseType}
        assert result.clause_type in valid_labels

    @patch("core.llm_client.get_structured_completion")
    def test_out_of_taxonomy_label_is_never_persisted(self, mock_completion):
        clause = ClauseFactory(clause_text="Some ambiguous clause text.")
        mock_completion.return_value = _classification_response(
            primary_label="not_a_real_clause_type", primary_confidence=0.95
        )

        result = classify_clause(clause=clause)

        # An out-of-taxonomy model label must never be stored as-is - it
        # is converted to needs_human_review, which is itself one of the
        # eight defined labels.
        assert result.clause_type == ClauseType.NEEDS_HUMAN_REVIEW.value
        assert result.clause_type != "not_a_real_clause_type"


class TestLowConfidenceClassificationEscalated:
    """Requirement: Low-confidence classification escalated."""

    @patch("core.llm_client.get_structured_completion")
    def test_confidence_below_threshold_escalates_regardless_of_label(self, mock_completion):
        # Scenario: Confidence below threshold
        clause = ClauseFactory(clause_text="Payment is due net 30 days from the invoice date.")
        below_threshold = settings.CLASSIFICATION_MIN_CONFIDENCE - 0.05
        mock_completion.return_value = _classification_response(
            primary_label="payment_schedule",
            primary_confidence=below_threshold,
            secondary_label="termination",
            secondary_confidence=0.05,  # margin is wide, only the threshold gate should fire
        )

        result = classify_clause(clause=clause)

        assert result.clause_type == ClauseType.NEEDS_HUMAN_REVIEW.value

    @patch("core.llm_client.get_structured_completion")
    def test_two_plausible_labels_too_close_to_call_escalates(self, mock_completion):
        # Scenario: Two plausible labels too close to call
        clause = ClauseFactory(clause_text="Payment is due net 30 days from the invoice date.")
        primary_confidence = max(settings.CLASSIFICATION_MIN_CONFIDENCE + 0.2, 0.8)
        secondary_confidence = primary_confidence - (settings.CLASSIFICATION_MIN_MARGIN / 2)
        mock_completion.return_value = _classification_response(
            primary_label="payment_schedule",
            primary_confidence=primary_confidence,
            secondary_label="penalty_late_fee",
            secondary_confidence=secondary_confidence,
        )

        result = classify_clause(clause=clause)

        assert result.clause_type == ClauseType.NEEDS_HUMAN_REVIEW.value

    @patch("core.llm_client.get_structured_completion")
    def test_confident_and_well_separated_label_is_persisted(self, mock_completion):
        """Sanity check: a clean classification is NOT escalated."""
        clause = ClauseFactory(clause_text="Payment is due net 30 days from the invoice date.")
        mock_completion.return_value = _classification_response(
            primary_label="payment_schedule",
            primary_confidence=0.9,
            secondary_label="termination",
            secondary_confidence=0.1,
        )

        result = classify_clause(clause=clause)

        assert result.clause_type == "payment_schedule"


class TestClassificationIsAuditable:
    """Requirement: Classification is auditable."""

    @patch("core.llm_client.get_structured_completion")
    def test_confidence_and_rationale_retrievable_after_classification(self, mock_completion):
        # Scenario: Classification rationale retrievable
        clause = ClauseFactory(clause_text="Payment is due net 30 days from the invoice date.")
        mock_completion.return_value = _classification_response(
            primary_label="payment_schedule",
            primary_confidence=0.87,
            rationale="Explicitly sets a payment due date tied to invoicing.",
        )

        classify_clause(clause=clause)

        reloaded = Clause.objects.get(id=clause.id)
        assert reloaded.classification_confidence == pytest.approx(0.87)
        assert reloaded.classification_rationale == (
            "Explicitly sets a payment due date tied to invoicing."
        )


class TestClassificationAuditLogEntry:
    """One AuditLogEntry (stage=2) per classify_clause call."""

    @patch("core.llm_client.get_structured_completion")
    def test_one_audit_log_entry_created_per_call(self, mock_completion):
        clause = ClauseFactory(clause_text="Payment is due net 30 days from the invoice date.")
        response = _classification_response()
        mock_completion.return_value = response

        classify_clause(clause=clause)

        entries = AuditLogEntry.objects.filter(contract=clause.contract, stage=2)
        assert entries.count() == 1
        entry = entries.get()
        assert entry.clause_id == clause.id
        assert entry.prompt_version == "clause-classification-v1"
        assert entry.llm_response_raw == response
