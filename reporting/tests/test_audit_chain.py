"""Tests for reporting.selectors.verify_audit_chain (task 6.2).

Spec: specs/pipeline/audit-log-integrity/spec.md. See
openspec/changes/add-audit-log-hash-chain/design.md ("The verification
command").
"""

from __future__ import annotations

import pytest

from contracts.tests.factories import ContractFactory
from pipeline.models import AuditLogEntry
from pipeline.services import create_audit_log_entry
from pipeline.tests.factories import AuditLogEntryFactory
from reporting.selectors import verify_audit_chain

pytestmark = pytest.mark.django_db


def _write_entry(contract, *, stage=1, prompt_version="v1", llm_response_raw=None):
    return create_audit_log_entry(
        contract=contract,
        clause=None,
        stage=stage,
        prompt_version=prompt_version,
        llm_response_raw=llm_response_raw if llm_response_raw is not None else {"ok": True},
        model_name="test-model",
        latency_ms=1,
    )


class TestUntamperedChainVerifiesClean:
    """Spec: Untampered chain verifies clean."""

    def test_a_clean_chain_passes_with_zero_breaks(self):
        contract = ContractFactory()
        _write_entry(contract, stage=1)
        _write_entry(contract, stage=2)
        _write_entry(contract, stage=3)

        result = verify_audit_chain(contract=contract)

        assert result.passed is True
        assert result.breaks == []
        assert result.entries_verified == 3
        assert result.entries_exempt == 0
        assert result.contracts_checked == 1

    def test_a_contract_with_no_entries_at_all_passes_trivially(self):
        contract = ContractFactory()

        result = verify_audit_chain(contract=contract)

        assert result.passed is True
        assert result.entries_verified == 0
        assert result.entries_exempt == 0


class TestEditedFieldBreaksChain:
    """Spec: An edited field breaks the chain from that point forward."""

    def test_directly_editing_llm_response_raw_is_detected(self):
        contract = ContractFactory()
        entry = _write_entry(contract, stage=1, llm_response_raw={"original": True})
        # Direct field edit, bypassing create_audit_log_entry entirely.
        AuditLogEntry.objects.filter(id=entry.id).update(
            llm_response_raw={"tampered": True}
        )

        result = verify_audit_chain(contract=contract)

        assert result.passed is False
        assert len(result.breaks) == 1
        broken = result.breaks[0]
        assert broken.entry_id == entry.id
        assert broken.contract_id == contract.id
        assert broken.chain_sequence == entry.chain_sequence
        assert broken.reason == "entry_hash_mismatch"

    def test_directly_editing_stage_is_detected(self):
        contract = ContractFactory()
        entry = _write_entry(contract, stage=1)
        AuditLogEntry.objects.filter(id=entry.id).update(stage=2)

        result = verify_audit_chain(contract=contract)

        assert result.passed is False
        assert result.breaks[0].reason == "entry_hash_mismatch"

    def test_break_does_not_prevent_verification_of_the_rest_of_the_chain_being_reported(self):
        """A tampered entry is reported; entries before it are unaffected."""
        contract = ContractFactory()
        first = _write_entry(contract, stage=1)
        second = _write_entry(contract, stage=2)
        AuditLogEntry.objects.filter(id=second.id).update(stage=99)

        result = verify_audit_chain(contract=contract)

        assert result.passed is False
        assert len(result.breaks) == 1
        assert result.breaks[0].entry_id == second.id
        assert result.entries_verified == 2  # both entries were checked
        assert first.id != second.id


class TestDeletedEntryIsDetectedAsABreak:
    """Spec: A deleted entry is detected as a break."""

    def test_deleting_a_mid_chain_entry_is_detected(self):
        contract = ContractFactory()
        _write_entry(contract, stage=1)
        middle = _write_entry(contract, stage=2)
        third = _write_entry(contract, stage=3)
        AuditLogEntry.objects.filter(id=middle.id).delete()

        result = verify_audit_chain(contract=contract)

        assert result.passed is False
        assert len(result.breaks) == 1
        broken = result.breaks[0]
        assert broken.entry_id == third.id
        assert broken.reason in {"chain_sequence_gap", "prev_hash_mismatch"}


class TestPreExistingEntryIsExemptNotPassing:
    """Spec: A pre-existing entry is reported as exempt, not as passing."""

    def test_contract_with_only_exempt_entries_reports_exempt_not_verified(self):
        contract = ContractFactory()
        AuditLogEntryFactory(contract=contract, stage=1)
        AuditLogEntryFactory(contract=contract, stage=2)

        result = verify_audit_chain(contract=contract)

        assert result.entries_exempt == 2
        assert result.entries_verified == 0
        assert result.passed is True
        assert result.breaks == []

    def test_mixed_contract_first_hashed_entry_starts_chain_at_genesis(self):
        """Spec: A mixed contract's chain begins at its first hashed entry."""
        from core.audit_hash import GENESIS_PREV_HASH

        contract = ContractFactory()
        AuditLogEntryFactory(contract=contract, stage=1)  # exempt, pre-existing
        AuditLogEntryFactory(contract=contract, stage=2)  # exempt, pre-existing
        first_hashed = _write_entry(contract, stage=3)

        result = verify_audit_chain(contract=contract)

        assert result.passed is True
        assert result.entries_exempt == 2
        assert result.entries_verified == 1
        assert first_hashed.prev_hash == GENESIS_PREV_HASH
        assert first_hashed.chain_sequence == 1


class TestScopingToOneContractIsIndependent:
    """Spec: Two contracts' chains are independent."""

    def test_scoping_to_one_contract_never_reports_the_other_contracts_breaks(self):
        contract_a = ContractFactory()
        contract_b = ContractFactory()
        _write_entry(contract_a, stage=1)
        broken_entry = _write_entry(contract_b, stage=1)
        AuditLogEntry.objects.filter(id=broken_entry.id).update(stage=99)

        result_a = verify_audit_chain(contract=contract_a)
        result_b = verify_audit_chain(contract=contract_b)

        assert result_a.passed is True
        assert result_a.breaks == []
        assert result_a.contracts_checked == 1

        assert result_b.passed is False
        assert len(result_b.breaks) == 1
        assert result_b.breaks[0].contract_id == contract_b.id

    def test_checking_all_contracts_reports_breaks_against_the_right_contract_only(self):
        contract_a = ContractFactory()
        contract_b = ContractFactory()
        _write_entry(contract_a, stage=1)
        broken_entry = _write_entry(contract_b, stage=1)
        AuditLogEntry.objects.filter(id=broken_entry.id).update(stage=99)

        result = verify_audit_chain()

        assert result.passed is False
        assert len(result.breaks) == 1
        assert result.breaks[0].contract_id == contract_b.id
        assert result.contracts_checked == 2
