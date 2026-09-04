"""Tests for core.audit_hash.compute_entry_hash.

`compute_entry_hash` only reads plain attributes off its `entry` argument
(`id`, `contract_id`, `clause_id`, `stage`, `prompt_version`,
`llm_response_raw`, `model_name`, `latency_ms`, `created_at`,
`chain_sequence`, `prev_hash`) - no database access - so these are pure unit
tests against a lightweight stand-in, mirroring the no-database style
`core/tests/test_llm_client.py` already uses for this app. See
openspec/changes/add-audit-log-hash-chain/design.md (Decision 3) and
specs/pipeline/audit-log-integrity/spec.md (Requirement: entry_hash is
computed by one function shared between every writer and the verifier).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from core.audit_hash import GENESIS_PREV_HASH, compute_entry_hash


@dataclass
class _FakeEntry:
    """Carries exactly the attributes `compute_entry_hash` reads.

    Structurally satisfies `core.audit_hash.HashableAuditLogEntry` - field
    types mirror that Protocol exactly (`prev_hash: str | None`, even
    though every entry built by `_make_entry` below sets a concrete value)
    so `compute_entry_hash(entry)` type-checks against this stand-in.
    """

    id: uuid.UUID
    contract_id: uuid.UUID
    clause_id: uuid.UUID | None
    stage: int
    prompt_version: str
    llm_response_raw: dict
    model_name: str
    latency_ms: int
    created_at: datetime
    chain_sequence: int | None
    prev_hash: str | None


def _make_entry(**overrides) -> _FakeEntry:
    base = _FakeEntry(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        contract_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        clause_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        stage=1,
        prompt_version="clause-segmentation-v1",
        llm_response_raw={"clauses": [{"text": "a clause"}]},
        model_name="gpt-test",
        latency_ms=123,
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        chain_sequence=1,
        prev_hash=GENESIS_PREV_HASH,
    )
    return replace(base, **overrides)


class TestComputeEntryHashDeterminism:
    def test_same_field_values_always_produce_the_same_hash(self):
        entry_a = _make_entry()
        entry_b = _make_entry()

        assert compute_entry_hash(entry_a) == compute_entry_hash(entry_b)

    def test_hash_is_a_64_character_hex_digest(self):
        entry = _make_entry()

        digest = compute_entry_hash(entry)

        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)


class TestComputeEntryHashSensitivity:
    """Changing any one hashed field must change the resulting hash."""

    def _assert_changing_field_changes_hash(self, **override) -> None:
        base = _make_entry()
        changed = replace(base, **override)

        assert compute_entry_hash(base) != compute_entry_hash(changed)

    def test_changing_stage_changes_hash(self):
        self._assert_changing_field_changes_hash(stage=2)

    def test_changing_llm_response_raw_changes_hash(self):
        self._assert_changing_field_changes_hash(llm_response_raw={"clauses": []})

    def test_changing_prev_hash_changes_hash(self):
        self._assert_changing_field_changes_hash(prev_hash="1" * 64)

    def test_changing_chain_sequence_changes_hash(self):
        self._assert_changing_field_changes_hash(chain_sequence=2)

    def test_changing_prompt_version_changes_hash(self):
        self._assert_changing_field_changes_hash(prompt_version="clause-segmentation-v2")

    def test_changing_model_name_changes_hash(self):
        self._assert_changing_field_changes_hash(model_name="a-different-model")

    def test_changing_latency_ms_changes_hash(self):
        self._assert_changing_field_changes_hash(latency_ms=999)

    def test_changing_clause_id_changes_hash(self):
        self._assert_changing_field_changes_hash(
            clause_id=uuid.UUID("44444444-4444-4444-4444-444444444444")
        )

    def test_changing_id_changes_hash(self):
        self._assert_changing_field_changes_hash(
            id=uuid.UUID("55555555-5555-5555-5555-555555555555")
        )

    def test_changing_contract_id_changes_hash(self):
        self._assert_changing_field_changes_hash(
            contract_id=uuid.UUID("66666666-6666-6666-6666-666666666666")
        )

    def test_changing_created_at_changes_hash(self):
        self._assert_changing_field_changes_hash(
            created_at=datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        )

    def test_null_clause_id_produces_a_different_hash_than_a_set_clause_id(self):
        base = _make_entry()
        with_null_clause = replace(base, clause_id=None)

        assert compute_entry_hash(base) != compute_entry_hash(with_null_clause)


class TestComputeEntryHashCanonicalSerialization:
    def test_llm_response_raw_key_order_does_not_affect_the_hash(self):
        """Dict insertion order must not change the hash - `sort_keys=True`."""
        entry_a = _make_entry(
            llm_response_raw={"a": 1, "b": 2, "c": {"x": 1, "y": 2}}
        )
        entry_b = _make_entry(
            llm_response_raw={"c": {"y": 2, "x": 1}, "b": 2, "a": 1}
        )

        assert compute_entry_hash(entry_a) == compute_entry_hash(entry_b)

    def test_nested_dict_key_order_does_not_affect_the_hash(self):
        entry_a = _make_entry(llm_response_raw={"outer": {"first": 1, "second": 2}})
        entry_b = _make_entry(llm_response_raw={"outer": {"second": 2, "first": 1}})

        assert compute_entry_hash(entry_a) == compute_entry_hash(entry_b)
