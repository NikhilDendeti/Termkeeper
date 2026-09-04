"""Tests for mismatch persistence and quote-grounded description generation.

Spec: specs/razorpay-integration/mismatch-flagging/spec.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings

from contracts.models import RazorpayReferenceType
from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.models import AuditLogEntry, TermType
from pipeline.selectors import get_audit_trail
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.models import MismatchType
from razorpay_integration.selectors import list_mismatch_flags_for_contract
from razorpay_integration.services import (
    _create_llm_described_mismatch_flag,
    _create_missing_platform_evidence_flag,
    _create_trigger_condition_unverifiable_flag,
    _generate_mismatch_description,
    _run_payout_crosscheck,
)
from razorpay_integration.tests.factories import PlatformRecordFactory

pytestmark = pytest.mark.django_db

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class TestDeterministicClassificationPrecedesLLM:
    """Requirement: Deterministic mismatch classification precedes any LLM involvement."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2, AMOUNT_MISMATCH_TOLERANCE_PCT=0.05)
    @patch("core.llm_client.get_structured_completion")
    def test_no_llm_call_when_comparison_produces_no_mismatch(self, mock_completion):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
        )
        PlatformRecordFactory(contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 1})
        PlatformRecordFactory(
            contract=contract,
            razorpay_created_at=_EPOCH + timedelta(days=30),
            payload={"amount": 1},
        )

        flags = _run_payout_crosscheck(contract=contract)

        assert flags == []
        mock_completion.assert_not_called()


class TestPersistedMismatchFlagLinksTermAndEvidence:
    """Requirement: Persisted MismatchFlag links term and platform evidence."""

    @patch("core.llm_client.get_structured_completion")
    def test_cadence_or_amount_mismatch_has_non_null_platform_record(self, mock_completion):
        mock_completion.return_value = {
            "description": "Mismatch found.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"amount": 1',
        }
        term = ExtractedTermFactory(
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
        )
        platform_record = PlatformRecordFactory(payload={"amount": 1})

        flag = _create_llm_described_mismatch_flag(
            mismatch_type=MismatchType.CADENCE_MISMATCH.value,
            extracted_term=term,
            platform_record=platform_record,
            expected_value={"numeric_value": 1, "unit": "month"},
            actual_value={"empirical_cadence_days": 7.0},
        )

        assert flag.extracted_term_id == term.id
        assert flag.platform_record_id == platform_record.id

    def test_missing_platform_evidence_has_null_platform_record(self):
        term = ExtractedTermFactory()

        flag = _create_missing_platform_evidence_flag(extracted_term=term, payout_record_count=0)

        assert flag.extracted_term_id == term.id
        assert flag.platform_record is None

    def test_trigger_condition_unverifiable_has_null_platform_record(self):
        term = ExtractedTermFactory(term_type=TermType.MILESTONE_TRIGGER)

        flag = _create_trigger_condition_unverifiable_flag(extracted_term=term)

        assert flag.extracted_term_id == term.id
        assert flag.platform_record is None


class TestQuoteGroundedDescriptionGeneration:
    """Requirement: Quote-grounded description generation."""

    @patch("core.llm_client.get_structured_completion")
    def test_description_uses_verbatim_quotes_from_both_sources(self, mock_completion):
        term = ExtractedTermFactory(
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
        )
        platform_record = PlatformRecordFactory(payload={"amount": 1})
        mock_completion.return_value = {
            "description": "Contract states monthly, but Payout history shows weekly.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"amount": 1',
        }

        description = _generate_mismatch_description(
            contract=term.clause.contract,
            clause=term.clause,
            mismatch_type=MismatchType.CADENCE_MISMATCH.value,
            extracted_term=term,
            platform_record=platform_record,
            expected_value={"numeric_value": 1, "unit": "month"},
            actual_value={"empirical_cadence_days": 7.0},
        )

        assert description == "Contract states monthly, but Payout history shows weekly."
        assert mock_completion.call_count == 1

    @patch("core.llm_client.get_structured_completion")
    def test_unverifiable_quote_falls_back_to_deterministic_template_after_one_retry(
        self, mock_completion
    ):
        term = ExtractedTermFactory(
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
        )
        platform_record = PlatformRecordFactory(payload={"amount": 1})
        # Neither attempt's quotes are actually present in their sources.
        mock_completion.return_value = {
            "description": "A hallucinated description.",
            "expected_quote": "this text is nowhere in the clause",
            "actual_quote": "this text is nowhere in the payload",
        }

        description = _generate_mismatch_description(
            contract=term.clause.contract,
            clause=term.clause,
            mismatch_type=MismatchType.CADENCE_MISMATCH.value,
            extracted_term=term,
            platform_record=platform_record,
            expected_value={"numeric_value": 1, "unit": "month"},
            actual_value={"empirical_cadence_days": 7.0},
        )

        # Exactly one retry (2 attempts total), then a deterministic fallback.
        assert mock_completion.call_count == 2
        assert description != "A hallucinated description."
        assert "cadence" in description.lower()


class TestMismatchTypeRestrictedToFixedTaxonomy:
    """Requirement: Mismatch type restricted to a fixed taxonomy."""

    def test_all_four_taxonomy_labels_are_valid_choices(self):
        assert {choice.value for choice in MismatchType} == {
            "cadence_mismatch",
            "amount_mismatch",
            "missing_platform_evidence",
            "trigger_condition_unverifiable",
        }


class TestEvidenceChainRetrievableAfterPipelineRun:
    """Requirement: Every MismatchFlag is queryable with its full evidence chain."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2)
    @patch("core.llm_client.get_structured_completion")
    def test_evidence_chain_retrievable_from_persisted_storage(self, mock_completion):
        mock_completion.return_value = {
            "description": "Contract states monthly, but Payout history shows weekly.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"amount": 1',
        }
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        term = ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
        )
        PlatformRecordFactory(contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 1})
        PlatformRecordFactory(
            contract=contract, razorpay_created_at=_EPOCH + timedelta(days=7), payload={"amount": 1}
        )

        created_flags = _run_payout_crosscheck(contract=contract)
        assert len(created_flags) == 1

        # Re-fetch everything from scratch, as a caller would after the
        # pipeline run has long since finished.
        stored_flags = list(list_mismatch_flags_for_contract(contract=contract))
        assert len(stored_flags) == 1
        flag = stored_flags[0]
        assert flag.extracted_term_id == term.id
        assert flag.platform_record is not None
        assert flag.description

        # The stage-4 AuditLogEntry backing the description is independently
        # retrievable via pipeline.selectors.get_audit_trail.
        audit_entries = list(get_audit_trail(contract=contract))
        stage_4_entries = [entry for entry in audit_entries if entry.stage == 4]
        assert len(stage_4_entries) == 1
        assert stage_4_entries[0].clause_id == clause.id


class TestAuditLogEntryPersistedForEachDescriptionCall:
    """Task 6.4: an AuditLogEntry(stage=4) is written for each LLM description call."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2, AMOUNT_MISMATCH_TOLERANCE_PCT=0.05)
    @patch("core.llm_client.get_structured_completion")
    def test_stage_4_audit_entries_appear_via_get_audit_trail(self, mock_completion):
        mock_completion.return_value = {
            "description": "Contract states monthly, but Payout history shows weekly.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"amount": 1',
        }
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
        )
        PlatformRecordFactory(contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 1})
        PlatformRecordFactory(
            contract=contract, razorpay_created_at=_EPOCH + timedelta(days=7), payload={"amount": 1}
        )

        _run_payout_crosscheck(contract=contract)

        assert AuditLogEntry.objects.filter(contract=contract, stage=4).count() == 1
        audit_trail = list(get_audit_trail(contract=contract))
        assert any(entry.stage == 4 for entry in audit_trail)

    def test_no_audit_entry_for_deterministic_only_flags(self):
        """missing_platform_evidence/trigger_condition_unverifiable never call the LLM."""
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_structured={"numeric_value": 1, "unit": "month"},
        )

        _run_payout_crosscheck(contract=contract)

        assert AuditLogEntry.objects.filter(contract=contract, stage=4).count() == 0


class TestNoDuplicateAuditLogWriteHelper:
    """Task 4.2: this module must not define its own `_create_audit_log_entry`.

    Every AuditLogEntry write routes through the one shared
    `pipeline.services.create_audit_log_entry` - see design.md
    (add-audit-log-hash-chain) - Risks ("any future edit ... that bypasses
    pipeline.services.create_audit_log_entry ... silently breaks the
    tamper-evidence guarantee without any test failing loudly"). This test
    exists so a future reintroduction of a duplicate write path fails
    loudly instead.
    """

    def test_razorpay_integration_services_has_no_private_audit_log_helper(self):
        import razorpay_integration.services as razorpay_integration_services

        assert not hasattr(razorpay_integration_services, "_create_audit_log_entry")


class TestStage4AuditLogEntryChainsCorrectly:
    """Task 4.3 / spec: Every stage's write populates the chain fields."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2, AMOUNT_MISMATCH_TOLERANCE_PCT=0.05)
    @patch("core.llm_client.get_structured_completion")
    def test_stage_4_entry_has_a_non_null_hash_chained_from_the_prior_entry(
        self, mock_completion
    ):
        from core.audit_hash import GENESIS_PREV_HASH, compute_entry_hash
        from pipeline.services import create_audit_log_entry

        mock_completion.return_value = {
            "description": "Contract states monthly, but Payout history shows weekly.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"amount": 1',
        }
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
        )
        PlatformRecordFactory(contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 1})
        PlatformRecordFactory(
            contract=contract, razorpay_created_at=_EPOCH + timedelta(days=7), payload={"amount": 1}
        )

        # This contract's stage 1-3 entry, written before stage 4 runs, so
        # stage 4's entry is expected to chain from it (not from genesis).
        stage_1_entry = create_audit_log_entry(
            contract=contract,
            clause=None,
            stage=1,
            prompt_version="clause-segmentation-v1",
            llm_response_raw={"clauses": []},
            model_name="test-model",
            latency_ms=1,
        )

        _run_payout_crosscheck(contract=contract)

        stage_4_entry = AuditLogEntry.objects.get(contract=contract, stage=4)
        assert stage_4_entry.entry_hash is not None
        assert stage_4_entry.entry_hash == compute_entry_hash(stage_4_entry)
        assert stage_4_entry.prev_hash == stage_1_entry.entry_hash
        assert stage_4_entry.prev_hash != GENESIS_PREV_HASH
        assert stage_4_entry.chain_sequence == stage_1_entry.chain_sequence + 1
