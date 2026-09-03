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


def list_extracted_terms_for_clause(*, clause: Clause) -> QuerySet[ExtractedTerm]:
    """List the ExtractedTerm rows extracted from a single Clause."""
    return ExtractedTerm.objects.filter(clause=clause).order_by("created_at")
