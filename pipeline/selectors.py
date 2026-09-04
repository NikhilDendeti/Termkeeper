"""Read-path selector functions for the `pipeline` app.

Every non-trivial read goes through a function here per project convention.
"""

from __future__ import annotations

from django.db.models import QuerySet

from contracts.models import Clause, Contract
from pipeline.models import AuditLogEntry, ExtractedTerm


def get_audit_trail(*, contract: Contract) -> QuerySet[AuditLogEntry]:
    """List a Contract's complete audit trail, ordered by stage then creation time.

    See specs/pipeline/audit-trail/spec.md (Audit trail queryable per
    contract).
    """
    return AuditLogEntry.objects.filter(contract=contract).order_by("stage", "created_at")


def get_chain_tip(*, contract: Contract) -> AuditLogEntry | None:
    """Return `contract`'s current hash-chain tip: its highest-`chain_sequence`
    hashed AuditLogEntry, or `None` if it has no hashed entries yet.

    Only entries with a non-null `entry_hash` are considered - a pre-existing
    chain-exempt row (null `prev_hash`/`entry_hash`/`chain_sequence`) is never
    treated as part of the chain, even if it is the only or most recent row
    for this contract. See
    openspec/changes/add-audit-log-hash-chain/design.md (Decision 2, Decision
    3) and specs/pipeline/audit-log-integrity/spec.md (Requirement: A mixed
    contract's chain begins at its first hashed entry). Called by
    `pipeline.services.create_audit_log_entry` under `select_for_update()`
    inside the same `transaction.atomic()` block that assigns the next
    entry's `chain_sequence`/`prev_hash`, so concurrent writers for the same
    contract cannot compute the same tip twice.
    """
    return (
        AuditLogEntry.objects.select_for_update()
        .filter(contract=contract, entry_hash__isnull=False)
        .order_by("-chain_sequence")
        .first()
    )


def list_extracted_terms_for_clause(*, clause: Clause) -> QuerySet[ExtractedTerm]:
    """List the ExtractedTerm rows extracted from a single Clause."""
    return ExtractedTerm.objects.filter(clause=clause).order_by("created_at")
