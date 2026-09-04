"""Tests for risk_scoring.services.score_clause (tasks 2.2, 3.1-3.4, 5.2, 5.4).

Every `core.llm_client.get_structured_completion` call is mocked - no
real network call is made. `core.llm_client.quote_is_verbatim` itself is
never mocked - it runs for real against the clause text supplied below, so
"grounded"/"unbacked" in each test name is literally true of the fixture
data.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from contracts.models import ClauseType
from contracts.tests.factories import ClauseFactory
from core import llm_client
from pipeline.models import AuditLogEntry
from risk_scoring.models import RiskAssessment, SeverityChoices
from risk_scoring.services import (
    _RISK_SCORING_PROMPT_VERSION,
    _RISK_SCORING_SCHEMA,
    _SHORT_CIRCUIT_EXPLANATION,
    _UNVERIFIED_EXPLANATION_FALLBACK,
    score_clause,
)

pytestmark = pytest.mark.django_db

CLAUSE_TEXT = (
    "5. Termination. Either party may terminate this Agreement upon 90 days "
    "written notice to the other party; provided, however, that Vendor may "
    "terminate immediately for any reason at Vendor's sole discretion."
)

_GROUNDED_QUOTE_1 = "terminate immediately for any reason at Vendor's sole discretion"
_GROUNDED_QUOTE_2 = "90 days written notice to the other party"
_UNBACKED_QUOTE = "this exact phrase never appears anywhere in the clause text"


def _grounded_response(*, asymmetry_score: float = 0.6, suggested_rewrite=None) -> dict:
    return {
        "sentences": [
            {
                "text": "The clause lets Vendor terminate immediately at its own discretion.",
                "quote": _GROUNDED_QUOTE_1,
            },
            {
                "text": "The counterparty must instead give 90 days written notice.",
                "quote": _GROUNDED_QUOTE_2,
            },
        ],
        "asymmetry_score": asymmetry_score,
        "suggested_rewrite": suggested_rewrite,
    }


def _unbacked_response(*, marker: str) -> dict:
    return {
        "sentences": [
            {"text": f"unbacked claim {marker}", "quote": _UNBACKED_QUOTE},
        ],
        "asymmetry_score": 0.6,
        "suggested_rewrite": "a rewrite that should never be persisted",
    }


class TestStage5Schema:
    """Task 3.1: schema/prompt_version definition, conforming response round-trips."""

    def test_prompt_version_is_a_non_empty_string(self):
        assert isinstance(_RISK_SCORING_PROMPT_VERSION, str) and _RISK_SCORING_PROMPT_VERSION

    def test_a_conforming_response_round_trips_through_the_schema_unchanged(self):
        response = _grounded_response(suggested_rewrite="Give both parties 90 days notice.")

        # Should not raise - the manual re-validator every stage's response
        # passes through inside core.llm_client.get_structured_completion.
        llm_client._validate_against_schema(
            response, _RISK_SCORING_SCHEMA, path="$", prompt_version=_RISK_SCORING_PROMPT_VERSION
        )

        assert response == _grounded_response(
            suggested_rewrite="Give both parties 90 days notice."
        )


class TestNeedsHumanReviewShortCircuit:
    """Task 2.2 / spec: Automatic human review inherited from classification."""

    @pytest.mark.parametrize("clause_type", [None, ClauseType.NEEDS_HUMAN_REVIEW.value])
    @patch("core.llm_client.get_structured_completion")
    def test_scoring_llm_is_never_called_and_severity_is_needs_human_review(
        self, mock_completion, clause_type
    ):
        clause = ClauseFactory(clause_type=clause_type, clause_text=CLAUSE_TEXT)

        assessment = score_clause(clause=clause)

        mock_completion.assert_not_called()
        assert assessment.severity == SeverityChoices.NEEDS_HUMAN_REVIEW.value
        assert assessment.asymmetry_score == 0.0
        assert assessment.suggested_rewrite is None
        assert assessment.explanation == _SHORT_CIRCUIT_EXPLANATION

    @patch("core.llm_client.get_structured_completion")
    def test_short_circuit_still_writes_exactly_one_stage_5_audit_log_entry(
        self, mock_completion
    ):
        clause = ClauseFactory(clause_type=None, clause_text=CLAUSE_TEXT)

        score_clause(clause=clause)

        entries = AuditLogEntry.objects.filter(contract=clause.contract, stage=5)
        assert entries.count() == 1
        assert entries.get().clause_id == clause.id


class TestQuoteGroundedExplanationPersists:
    """Task 3.2 / spec: fully grounded explanation persists as scored."""

    @patch("core.llm_client.get_structured_completion")
    def test_every_quote_verbatim_persists_explanation_and_formula_severity(
        self, mock_completion
    ):
        mock_completion.return_value = _grounded_response(
            asymmetry_score=0.6, suggested_rewrite="Give both parties equal notice periods."
        )
        clause = ClauseFactory(clause_type=ClauseType.TERMINATION.value, clause_text=CLAUSE_TEXT)

        assessment = score_clause(clause=clause)

        mock_completion.assert_called_once()
        assert assessment.severity != SeverityChoices.NEEDS_HUMAN_REVIEW.value
        assert assessment.asymmetry_score == 0.6
        assert _GROUNDED_QUOTE_1 in clause.clause_text
        assert "terminate immediately at its own discretion" in assessment.explanation
        assert "90 days written notice" in assessment.explanation

        entries = AuditLogEntry.objects.filter(contract=clause.contract, stage=5)
        assert entries.count() == 1


class TestUnbackedQuoteForcesHumanReviewAfterOneRetry:
    """Task 3.3 / spec: unbacked sentence forces human review after one retry."""

    @patch("core.llm_client.get_structured_completion")
    def test_two_consecutive_unbacked_responses_force_needs_human_review(self, mock_completion):
        mock_completion.side_effect = [
            _unbacked_response(marker="attempt-1"),
            _unbacked_response(marker="attempt-2"),
        ]
        clause = ClauseFactory(clause_type=ClauseType.TERMINATION.value, clause_text=CLAUSE_TEXT)

        assessment = score_clause(clause=clause)

        assert mock_completion.call_count == 2
        assert assessment.severity == SeverityChoices.NEEDS_HUMAN_REVIEW.value
        assert assessment.explanation == _UNVERIFIED_EXPLANATION_FALLBACK
        assert "unbacked claim" not in assessment.explanation
        assert assessment.asymmetry_score == 0.0
        assert assessment.suggested_rewrite is None

    @patch("core.llm_client.get_structured_completion")
    def test_forced_review_still_writes_exactly_one_stage_5_audit_log_entry(
        self, mock_completion
    ):
        mock_completion.side_effect = [
            _unbacked_response(marker="attempt-1"),
            _unbacked_response(marker="attempt-2"),
        ]
        clause = ClauseFactory(clause_type=ClauseType.TERMINATION.value, clause_text=CLAUSE_TEXT)

        score_clause(clause=clause)

        assert AuditLogEntry.objects.filter(contract=clause.contract, stage=5).count() == 1


class TestUnbackedFirstAttemptGroundedRetryPersistsRetriedResult:
    """Task 3.4: first attempt unbacked, retry fully grounded."""

    @patch("core.llm_client.get_structured_completion")
    def test_retried_explanation_persists_with_formula_derived_severity(self, mock_completion):
        mock_completion.side_effect = [
            _unbacked_response(marker="attempt-1"),
            _grounded_response(asymmetry_score=0.6, suggested_rewrite="A fairer notice term."),
        ]
        clause = ClauseFactory(clause_type=ClauseType.TERMINATION.value, clause_text=CLAUSE_TEXT)

        assessment = score_clause(clause=clause)

        assert mock_completion.call_count == 2
        assert assessment.severity != SeverityChoices.NEEDS_HUMAN_REVIEW.value
        assert "unbacked claim" not in assessment.explanation
        assert "terminate immediately at its own discretion" in assessment.explanation
        assert assessment.asymmetry_score == 0.6

        # Exactly one AuditLogEntry despite two Claude calls within this
        # single score_clause invocation - matches phase 1's segmentation
        # pattern (multiple attempts, one audit entry per call).
        entries = AuditLogEntry.objects.filter(contract=clause.contract, stage=5)
        assert entries.count() == 1


class TestSuggestedRewriteGate:
    """Task 5.2 / spec: Suggested rewrite scoped to actionable severity."""

    @patch("core.llm_client.get_structured_completion")
    def test_low_severity_has_no_rewrite_even_if_model_supplied_one(self, mock_completion):
        # `other` has the lowest criticality weight (0.3); a small asymmetry
        # score keeps `base` under the low/medium boundary (0.25).
        mock_completion.return_value = _grounded_response(
            asymmetry_score=0.2, suggested_rewrite="should be dropped by the severity gate"
        )
        clause = ClauseFactory(clause_type=ClauseType.OTHER.value, clause_text=CLAUSE_TEXT)

        assessment = score_clause(clause=clause)

        assert assessment.severity == SeverityChoices.LOW.value
        assert assessment.suggested_rewrite is None

    @patch("core.llm_client.get_structured_completion")
    def test_needs_human_review_has_no_rewrite(self, mock_completion):
        clause = ClauseFactory(clause_type=None, clause_text=CLAUSE_TEXT)

        assessment = score_clause(clause=clause)

        assert assessment.severity == SeverityChoices.NEEDS_HUMAN_REVIEW.value
        assert assessment.suggested_rewrite is None

    @pytest.mark.parametrize("asymmetry_score", [0.5, 0.7, 0.95])
    @patch("core.llm_client.get_structured_completion")
    def test_actionable_severity_includes_a_non_empty_rewrite(
        self, mock_completion, asymmetry_score
    ):
        mock_completion.return_value = _grounded_response(
            asymmetry_score=asymmetry_score, suggested_rewrite="Give both parties equal notice."
        )
        clause = ClauseFactory(
            clause_type=ClauseType.PAYMENT_SCHEDULE.value, clause_text=CLAUSE_TEXT
        )

        assessment = score_clause(clause=clause)

        assert assessment.severity in {
            SeverityChoices.MEDIUM.value,
            SeverityChoices.HIGH.value,
            SeverityChoices.CRITICAL.value,
        }
        assert assessment.suggested_rewrite == "Give both parties equal notice."


class TestScoreClauseIsIdempotentPerClause:
    """Re-running score_clause updates the one current RiskAssessment (not an append)."""

    @patch("core.llm_client.get_structured_completion")
    def test_running_twice_leaves_exactly_one_current_assessment(self, mock_completion):
        mock_completion.return_value = _grounded_response(asymmetry_score=0.4)
        clause = ClauseFactory(clause_type=ClauseType.TERMINATION.value, clause_text=CLAUSE_TEXT)

        first = score_clause(clause=clause)
        mock_completion.return_value = _grounded_response(asymmetry_score=0.9)
        second = score_clause(clause=clause)

        assert first.id == second.id
        assert RiskAssessment.objects.filter(clause=clause).count() == 1
        assert RiskAssessment.objects.get(clause=clause).asymmetry_score == 0.9


class TestNoDuplicateAuditLogWriteHelper:
    """Task 5.2: this module must not define its own `_create_audit_log_entry`.

    Mirrors razorpay_integration's test of the same shape - every
    AuditLogEntry write routes through the one shared
    `pipeline.services.create_audit_log_entry`. See design.md
    (add-audit-log-hash-chain) - Risks.
    """

    def test_risk_scoring_services_has_no_private_audit_log_helper(self):
        import risk_scoring.services as risk_scoring_services

        assert not hasattr(risk_scoring_services, "_create_audit_log_entry")


class TestStage5AuditLogEntryChainsCorrectly:
    """Task 5.3 / spec: Every stage's write populates the chain fields."""

    def test_short_circuit_path_entry_chains_from_the_contracts_prior_entry(self):
        from core.audit_hash import compute_entry_hash
        from pipeline.services import create_audit_log_entry

        clause = ClauseFactory(clause_type=None, clause_text=CLAUSE_TEXT)
        prior = create_audit_log_entry(
            contract=clause.contract,
            clause=None,
            stage=1,
            prompt_version="clause-segmentation-v1",
            llm_response_raw={"clauses": []},
            model_name="test-model",
            latency_ms=1,
        )

        score_clause(clause=clause)

        stage_5_entry = AuditLogEntry.objects.get(contract=clause.contract, stage=5)
        assert stage_5_entry.entry_hash is not None
        assert stage_5_entry.entry_hash == compute_entry_hash(stage_5_entry)
        assert stage_5_entry.prev_hash == prior.entry_hash
        assert stage_5_entry.chain_sequence == prior.chain_sequence + 1

    @patch("core.llm_client.get_structured_completion")
    def test_main_path_entry_chains_from_the_contracts_prior_entry(self, mock_completion):
        from core.audit_hash import compute_entry_hash
        from pipeline.services import create_audit_log_entry

        mock_completion.return_value = _grounded_response(asymmetry_score=0.6)
        clause = ClauseFactory(clause_type=ClauseType.TERMINATION.value, clause_text=CLAUSE_TEXT)
        prior = create_audit_log_entry(
            contract=clause.contract,
            clause=None,
            stage=1,
            prompt_version="clause-segmentation-v1",
            llm_response_raw={"clauses": []},
            model_name="test-model",
            latency_ms=1,
        )

        score_clause(clause=clause)

        stage_5_entry = AuditLogEntry.objects.get(contract=clause.contract, stage=5)
        assert stage_5_entry.entry_hash is not None
        assert stage_5_entry.entry_hash == compute_entry_hash(stage_5_entry)
        assert stage_5_entry.prev_hash == prior.entry_hash
        assert stage_5_entry.chain_sequence == prior.chain_sequence + 1

    def test_stage_5_first_hashed_entry_for_a_contract_with_exempt_prior_entries(self):
        """A contract whose stage 1-4 entries pre-date this capability (exempt,
        null-hash) and whose first-ever hashed entry is stage 5's - the chain
        must start from genesis at that entry, not treat the exempt entries as
        part of the chain. Spec: A mixed contract's chain begins at its first
        hashed entry.
        """
        from core.audit_hash import GENESIS_PREV_HASH, compute_entry_hash
        from pipeline.tests.factories import AuditLogEntryFactory

        clause = ClauseFactory(clause_type=None, clause_text=CLAUSE_TEXT)
        # Exempt (pre-existing, null-hash) entries for stages 1-4 - as if
        # this contract was fully processed before hash-chain verification
        # existed, and is now merely being (re-)scored for stage 5.
        for stage in (1, 2, 3, 4):
            AuditLogEntryFactory(contract=clause.contract, stage=stage)

        score_clause(clause=clause)

        stage_5_entry = AuditLogEntry.objects.get(contract=clause.contract, stage=5)
        assert stage_5_entry.entry_hash is not None
        assert stage_5_entry.entry_hash == compute_entry_hash(stage_5_entry)
        assert stage_5_entry.prev_hash == GENESIS_PREV_HASH
        assert stage_5_entry.chain_sequence == 1
