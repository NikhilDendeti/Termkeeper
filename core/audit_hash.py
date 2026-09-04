"""Canonical hash computation for the per-Contract AuditLogEntry hash chain.

A small, model-free module - the same "shared, model-free utility" role
`core/llm_client.py` already plays for the pipeline. Both the writer
(`pipeline.services.create_audit_log_entry`) and the verifier
(`reporting.selectors.verify_audit_chain`) import `compute_entry_hash` from
here and call it identically - this is the single source of truth for the
hash formula so the two sides can never independently drift apart. See
openspec/changes/add-audit-log-hash-chain/design.md (Decision 3) and
specs/pipeline/audit-log-integrity/spec.md (Requirement: entry_hash is
computed by one function shared between every writer and the verifier).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Protocol


class HashableAuditLogEntry(Protocol):
    """The structural shape `compute_entry_hash` needs from an entry.

    Deliberately a `Protocol`, not `pipeline.models.AuditLogEntry` directly -
    this module stays model-free (no import of any Django app, matching the
    module docstring above): any object with these attributes - a real
    `AuditLogEntry` instance, or a lightweight test double - can be hashed
    identically. `pipeline.models.AuditLogEntry` satisfies this structurally,
    with no explicit inheritance needed.
    """

    id: uuid.UUID
    contract_id: uuid.UUID
    clause_id: uuid.UUID | None
    stage: int
    prompt_version: str
    llm_response_raw: Any
    model_name: str
    latency_ms: int
    created_at: datetime
    chain_sequence: int | None
    prev_hash: str | None


# 64 hex chars, the same length as a real SHA-256 digest - the `prev_hash`
# for a contract's first hashed AuditLogEntry.
GENESIS_PREV_HASH = "0" * 64

# Bumped only when the set of fields hashed below changes - included inside
# the hashed payload itself so any future change to the formula changes
# every subsequently-computed hash visibly and intentionally, rather than
# silently reinterpreting old hashes under new rules. See design.md
# (Decision 3) and design.md - Risks ("hash_schema_version bumps are a
# manual discipline, not enforced by anything").
HASH_SCHEMA_VERSION = 1


def compute_entry_hash(entry: HashableAuditLogEntry) -> str:
    """Compute `entry`'s canonical hash: sha256(prev_hash + canonical_json(payload)).

    `prev_hash` is prepended as a raw string to the canonical JSON bytes, not
    embedded inside the JSON object - the formula is literally string
    concatenation followed by one hash. `json.dumps(..., sort_keys=True,
    separators=(",", ":"))` makes the serialization byte-for-byte
    deterministic regardless of dict insertion order (Python dict field
    order varies across code paths - `llm_response_raw` in particular is
    parsed JSON from an LLM API response). Every hashed field is read from
    `entry`'s own persisted attributes - never recomputed or looked up
    elsewhere - so the same row always produces the same hash.

    `entry.prev_hash` must already be set (to `GENESIS_PREV_HASH` or a
    prior entry's `entry_hash`) before calling this - the writer
    (`pipeline.services.create_audit_log_entry`) always sets it first, and
    the verifier (`reporting.selectors.verify_audit_chain`) only calls this
    for rows that already have a non-null `prev_hash`. The field is
    nullable at the model/Protocol level only because a chain-exempt
    pre-existing row has no hash at all.
    """
    assert entry.prev_hash is not None, (
        "compute_entry_hash requires entry.prev_hash to already be set"
    )
    payload = {
        "hash_schema_version": HASH_SCHEMA_VERSION,
        "id": str(entry.id),
        "contract_id": str(entry.contract_id),
        "clause_id": str(entry.clause_id) if entry.clause_id else None,
        "stage": entry.stage,
        "prompt_version": entry.prompt_version,
        "llm_response_raw": entry.llm_response_raw,
        "model_name": entry.model_name,
        "latency_ms": entry.latency_ms,
        "created_at": entry.created_at.isoformat(),
        "chain_sequence": entry.chain_sequence,
    }
    canonical_json = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256((entry.prev_hash + canonical_json).encode("utf-8")).hexdigest()
