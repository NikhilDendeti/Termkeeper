"""Tests for the AuditLogEntry hash chain: pipeline.selectors.get_chain_tip
and pipeline.services.create_audit_log_entry (tasks 3.1, 3.4, 3.5).

Spec: specs/pipeline/audit-log-integrity/spec.md. See
openspec/changes/add-audit-log-hash-chain/design.md (Decisions 1-3).
"""

from __future__ import annotations

import threading
import time

import pytest
from django.db import connections
from django.db.utils import OperationalError

from contracts.tests.factories import ContractFactory
from core.audit_hash import GENESIS_PREV_HASH, compute_entry_hash
from pipeline.models import AuditLogEntry, PipelineStage
from pipeline.selectors import get_chain_tip
from pipeline.services import create_audit_log_entry
from pipeline.tests.factories import AuditLogEntryFactory

pytestmark = pytest.mark.django_db


def _create_hashed_entry(*, contract, chain_sequence, prev_hash, stage=1):
    """Directly persist a well-formed hashed AuditLogEntry for test setup.

    Bypasses `create_audit_log_entry` deliberately - these tests build a
    known chain state to exercise `get_chain_tip` in isolation.
    """
    entry = AuditLogEntry.objects.create(
        contract=contract,
        clause=None,
        stage=stage,
        prompt_version="test-prompt-v1",
        llm_response_raw={"ok": True},
        model_name="test-model",
        latency_ms=10,
        prev_hash=prev_hash,
        chain_sequence=chain_sequence,
    )
    entry.entry_hash = compute_entry_hash(entry)
    entry.save(update_fields=["entry_hash"])
    return entry


class TestGetChainTip:
    """Task 3.1."""

    def test_returns_none_when_contract_has_no_entries_at_all(self):
        contract = ContractFactory()

        assert get_chain_tip(contract=contract) is None

    def test_returns_none_when_contract_has_only_exempt_entries(self):
        contract = ContractFactory()
        AuditLogEntryFactory(contract=contract, stage=1)
        AuditLogEntryFactory(contract=contract, stage=2)

        assert get_chain_tip(contract=contract) is None

    def test_returns_the_highest_chain_sequence_hashed_entry_in_a_mix(self):
        contract = ContractFactory()
        # Exempt (pre-existing) entries first, mirroring a mixed contract.
        AuditLogEntryFactory(contract=contract, stage=1)
        AuditLogEntryFactory(contract=contract, stage=2)

        first_hashed = _create_hashed_entry(
            contract=contract, chain_sequence=1, prev_hash=GENESIS_PREV_HASH
        )
        second_hashed = _create_hashed_entry(
            contract=contract, chain_sequence=2, prev_hash=first_hashed.entry_hash
        )

        tip = get_chain_tip(contract=contract)

        assert tip is not None
        assert tip.id == second_hashed.id
        assert tip.chain_sequence == 2

    def test_only_considers_entries_for_the_given_contract(self):
        contract_a = ContractFactory()
        contract_b = ContractFactory()
        _create_hashed_entry(contract=contract_a, chain_sequence=1, prev_hash=GENESIS_PREV_HASH)

        assert get_chain_tip(contract=contract_b) is None


class TestCreateAuditLogEntryGenesis:
    """Task 3.4 (first part) / spec: A contract's first hashed entry chains from genesis."""

    def test_first_entry_for_a_contract_gets_genesis_prev_hash_and_sequence_one(self):
        contract = ContractFactory()

        entry = create_audit_log_entry(
            contract=contract,
            clause=None,
            stage=PipelineStage.SEGMENTATION,
            prompt_version="clause-segmentation-v1",
            llm_response_raw={"clauses": []},
            model_name="test-model",
            latency_ms=50,
        )

        assert entry.prev_hash == GENESIS_PREV_HASH
        assert entry.chain_sequence == 1
        assert entry.entry_hash is not None
        assert entry.entry_hash == compute_entry_hash(entry)


class TestCreateAuditLogEntryChaining:
    """Task 3.4 (second part) / spec: Later entries chain to the immediately
    prior entry for the same contract."""

    def test_second_entry_chains_to_the_first(self):
        contract = ContractFactory()

        first = create_audit_log_entry(
            contract=contract,
            clause=None,
            stage=PipelineStage.SEGMENTATION,
            prompt_version="clause-segmentation-v1",
            llm_response_raw={"clauses": []},
            model_name="test-model",
            latency_ms=50,
        )
        second = create_audit_log_entry(
            contract=contract,
            clause=None,
            stage=PipelineStage.CLASSIFICATION,
            prompt_version="clause-classification-v1",
            llm_response_raw={"primary_label": "termination"},
            model_name="test-model",
            latency_ms=75,
        )

        assert second.prev_hash == first.entry_hash
        assert second.chain_sequence == first.chain_sequence + 1 == 2

    def test_third_entry_chains_to_the_second_not_the_first(self):
        contract = ContractFactory()

        first = create_audit_log_entry(
            contract=contract,
            clause=None,
            stage=1,
            prompt_version="v1",
            llm_response_raw={},
            model_name="test-model",
            latency_ms=1,
        )
        second = create_audit_log_entry(
            contract=contract,
            clause=None,
            stage=2,
            prompt_version="v1",
            llm_response_raw={},
            model_name="test-model",
            latency_ms=1,
        )
        third = create_audit_log_entry(
            contract=contract,
            clause=None,
            stage=3,
            prompt_version="v1",
            llm_response_raw={},
            model_name="test-model",
            latency_ms=1,
        )

        assert first.prev_hash == GENESIS_PREV_HASH
        assert third.prev_hash == second.entry_hash
        assert third.prev_hash != first.entry_hash
        assert [first.chain_sequence, second.chain_sequence, third.chain_sequence] == [1, 2, 3]


class TestCreateAuditLogEntryPerContractIsolation:
    """Task 3.5 / spec: Two contracts' chains are independent."""

    def test_two_contracts_chains_never_reference_each_other(self):
        contract_a = ContractFactory()
        contract_b = ContractFactory()

        entry_a1 = create_audit_log_entry(
            contract=contract_a,
            clause=None,
            stage=1,
            prompt_version="v1",
            llm_response_raw={"who": "a"},
            model_name="test-model",
            latency_ms=1,
        )
        entry_b1 = create_audit_log_entry(
            contract=contract_b,
            clause=None,
            stage=1,
            prompt_version="v1",
            llm_response_raw={"who": "b"},
            model_name="test-model",
            latency_ms=1,
        )
        entry_a2 = create_audit_log_entry(
            contract=contract_a,
            clause=None,
            stage=2,
            prompt_version="v1",
            llm_response_raw={"who": "a"},
            model_name="test-model",
            latency_ms=1,
        )

        # Both contracts' first entries independently chain from genesis.
        assert entry_a1.prev_hash == GENESIS_PREV_HASH
        assert entry_b1.prev_hash == GENESIS_PREV_HASH
        assert entry_a1.chain_sequence == 1
        assert entry_b1.chain_sequence == 1

        # contract_a's second entry chains to contract_a's first entry only.
        assert entry_a2.prev_hash == entry_a1.entry_hash
        assert entry_a2.prev_hash != entry_b1.entry_hash
        assert entry_a2.chain_sequence == 2

        # contract_b's chain tip is unaffected by contract_a's writes.
        assert get_chain_tip(contract=contract_b).id == entry_b1.id
        assert get_chain_tip(contract=contract_a).id == entry_a2.id


class TestConcurrentWritesToTheSameContractDoNotForkTheChain:
    """`select_for_update()` inside `get_chain_tip` (design.md - Decision 3,
    step 1) exists precisely so two concurrent writers for the same
    contract cannot both read the same chain tip and each mint an entry
    claiming the same `chain_sequence`/`prev_hash`, forking the chain.

    This spins up real OS threads, each with its own DB connection (which
    is why this uses `@pytest.mark.django_db(transaction=True)`, overriding
    the module's default non-transactional `django_db` for this one test -
    a plain `django_db` test runs everything inside one wrapped transaction
    on a single connection, which a second thread's own connection would
    never see; `transaction=True` gives each thread's connection a real,
    independently-committed view of the database, the only way to actually
    exercise cross-connection contention on `get_chain_tip`'s
    `select_for_update()` query), all racing to extend the very same
    contract's chain concurrently, and asserts the result is one clean,
    unbroken sequence - no duplicate `chain_sequence`, no forked
    `prev_hash`, regardless of write interleaving.

    SQLite itself (this project's only backend - see design.md
    add-django-foundation) has no row-level locking, so `select_for_update()`
    is a no-op on it (`DatabaseFeatures.has_select_for_update = False` -
    confirmed against this project's installed Django) - contention here is
    instead resolved by SQLite's own coarser, whole-table locking, which
    surfaces as a transient `OperationalError` ("database table is locked")
    to a losing thread rather than a silent fork. The retry loop below
    mirrors the retry-on-contention pattern any real caller of a
    short-lived write transaction needs against SQLite; what this test
    actually proves - the property `select_for_update()` +
    `transaction.atomic()` exist to guarantee - is the *outcome*: whichever
    write order actually happens, every writer that succeeds lands on a
    distinct `chain_sequence`, and the chain that results is one clean,
    unbroken line, never two entries silently sharing a `chain_sequence` or
    forking `prev_hash`.
    """

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_writers_for_the_same_contract_produce_one_clean_chain(self):
        contract = ContractFactory()
        thread_count = 8
        max_attempts_per_writer = 25
        errors: list[BaseException] = []
        barrier = threading.Barrier(thread_count)

        def _write(index: int) -> None:
            try:
                # Every thread waits here so as many writers as possible are
                # actually racing to call get_chain_tip/create at once,
                # rather than trivially running one after another.
                barrier.wait(timeout=10)
                for attempt in range(max_attempts_per_writer):
                    try:
                        create_audit_log_entry(
                            contract=contract,
                            clause=None,
                            stage=1,
                            prompt_version="v1",
                            llm_response_raw={"writer_index": index},
                            model_name="test-model",
                            latency_ms=1,
                        )
                        return
                    except OperationalError as exc:
                        if "locked" not in str(exc).lower():
                            raise
                        if attempt == max_attempts_per_writer - 1:
                            raise
                        # SQLite's whole-table locking under contention
                        # (not row-level locking - see class docstring):
                        # back off briefly and let the current holder finish.
                        time.sleep(0.02)
            except BaseException as exc:  # noqa: BLE001 - surfaced to the main thread below
                errors.append(exc)
            finally:
                # Each thread gets its own Django DB connection implicitly;
                # close it explicitly so none are left dangling - see
                # Django's docs on using the ORM from multiple threads.
                connections.close_all()

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert errors == [], f"writer thread(s) raised: {errors!r}"

        entries = list(
            AuditLogEntry.objects.filter(contract=contract).order_by("chain_sequence")
        )
        # No two threads were assigned the same chain_sequence, and none was
        # skipped: exactly one entry per writer, forming 1..thread_count.
        assert len(entries) == thread_count
        assert [entry.chain_sequence for entry in entries] == list(range(1, thread_count + 1))

        # The chain is a single unbroken line, not forked: each entry's
        # prev_hash equals the immediately preceding entry's entry_hash (or
        # genesis for the first), and every stored entry_hash is still
        # exactly what recomputation from that row's own fields produces.
        expected_prev = GENESIS_PREV_HASH
        for entry in entries:
            assert entry.prev_hash == expected_prev
            assert entry.entry_hash == compute_entry_hash(entry)
            expected_prev = entry.entry_hash
