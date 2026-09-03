"""Read-path selector functions for the `razorpay_integration` app.

Every non-trivial read goes through a function here per project convention.
"""

from __future__ import annotations

from django.db.models import QuerySet

from contracts.models import Contract
from razorpay_integration.models import MismatchFlag, PlatformRecord, PlatformRecordType


def get_platform_records_for_contract(
    *, contract: Contract, record_type: str | None = None
) -> QuerySet[PlatformRecord]:
    """List a Contract's PlatformRecords, optionally filtered to one record_type."""
    queryset = PlatformRecord.objects.filter(contract=contract)
    if record_type is not None:
        queryset = queryset.filter(record_type=record_type)
    return queryset.order_by("razorpay_created_at")


def list_mismatch_flags_for_contract(*, contract: Contract) -> QuerySet[MismatchFlag]:
    """List every MismatchFlag traceable back to a Contract via its ExtractedTerm.

    See specs/razorpay-integration/mismatch-flagging/spec.md (Requirement:
    Every MismatchFlag is queryable with its full evidence chain).
    """
    return MismatchFlag.objects.filter(extracted_term__clause__contract=contract).order_by(
        "created_at"
    )


def get_latest_payout_records(
    *, contract: Contract, minimum: int = 2
) -> QuerySet[PlatformRecord]:
    """Return the Contract's payout PlatformRecords, ordered oldest-first.

    Returns an empty queryset if fewer than `minimum` payout records exist,
    so callers can treat "not enough evidence" as an empty result rather
    than checking `.count()` themselves.
    """
    queryset = get_platform_records_for_contract(
        contract=contract, record_type=PlatformRecordType.PAYOUT
    )
    if queryset.count() < minimum:
        return PlatformRecord.objects.none()
    return queryset
