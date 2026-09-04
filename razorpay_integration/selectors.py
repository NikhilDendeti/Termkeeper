"""Read-path selector functions for the `razorpay_integration` app.

Every non-trivial read goes through a function here per project convention.

`term_unit`, `term_numeric_value`, `is_cadence_term`, `is_amount_term`,
`TIME_UNITS`, and `DAYS_PER_UNIT` were promoted here (public, no longer
underscore-prefixed) from `razorpay_integration/services.py` in
add-overdue-payment-detection. Classifying an `ExtractedTerm`'s
`value_structured` as a cadence or an amount is a pure read/computation over
already-persisted data - it belongs in this reads module, not the writes
module, per this project's established services.py-writes / selectors.py-
reads convention (the same reasoning add-audit-log-hash-chain already
applied when it collapsed the three duplicate `_create_audit_log_entry`
write helpers into one). `services.py` now imports these from here instead
of defining its own copies; behavior is unchanged, only location and
visibility. See openspec/changes/add-overdue-payment-detection/design.md.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone as django_timezone

from contracts import selectors as contracts_selectors
from contracts.models import Contract, RazorpayReferenceType
from pipeline import selectors as pipeline_selectors
from pipeline.models import ExtractedTerm, TermType
from razorpay_integration.models import MismatchFlag, PlatformRecord, PlatformRecordType

# ---------------------------------------------------------------------------
# Term-type <-> platform-field mapping heuristics
# ---------------------------------------------------------------------------
#
# Phase 1's fixed TermType taxonomy (payout_frequency, milestone_trigger,
# penalty_amount, notice_period, auto_renewal_term) has no separate "payout
# amount" term type - `payout_frequency` is the only term type this app
# compares against platform data, on either the cross-check paths in
# services.py or the live overdue-detection read below. A payout_frequency
# term's `value_structured` is always a single {numeric_value, unit} pair,
# so this module classifies each such term as either a *cadence* term (its
# `unit` names a recognized time unit) or an *amount* term (any other unit,
# including none) - see `is_cadence_term` / `is_amount_term`.

TIME_UNITS: frozenset[str] = frozenset(
    {"day", "days", "week", "weeks", "month", "months", "year", "years"}
)
DAYS_PER_UNIT: dict[str, float] = {
    "day": 1.0,
    "days": 1.0,
    "week": 7.0,
    "weeks": 7.0,
    "month": 30.0,
    "months": 30.0,
    "year": 365.0,
    "years": 365.0,
}


def term_unit(term: ExtractedTerm) -> str | None:
    value_structured = term.value_structured or {}
    unit = value_structured.get("unit")
    if isinstance(unit, str) and unit.strip():
        return unit.strip().lower()
    return None


def term_numeric_value(term: ExtractedTerm) -> float | None:
    value_structured = term.value_structured or {}
    numeric_value = value_structured.get("numeric_value")
    if numeric_value is None:
        return None
    return float(numeric_value)


def is_cadence_term(term: ExtractedTerm) -> bool:
    """Whether a payout_frequency term states a time interval (vs an amount)."""
    unit = term_unit(term)
    return unit is not None and unit in TIME_UNITS


def is_amount_term(term: ExtractedTerm) -> bool:
    """Whether a payout_frequency term states a numeric amount (vs a cadence)."""
    return term_numeric_value(term) is not None and not is_cadence_term(term)


# ---------------------------------------------------------------------------
# PlatformRecord / MismatchFlag reads
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Live overdue-payment detection
# (spec: razorpay-integration/overdue-payment-detection)
# ---------------------------------------------------------------------------
#
# Deliberately NOT a persisted MismatchFlag and NOT computed during stage 4
# (`services.detect_mismatches`) - "overdue" is a function of the calendar,
# not of any new evidence, so a contract that is not overdue today can
# become overdue next week with zero new pipeline activity. This reads rows
# that a prior real stage-4 run already persisted (ExtractedTerm,
# PlatformRecord) and recomputes fresh on every call - the same
# recompute-don't-trust pattern `reporting.selectors.verify_audit_chain` and
# `scan_razorpay_guardrail` already use. See
# openspec/changes/add-overdue-payment-detection/design.md.


@dataclass(frozen=True)
class OverdueStatus:
    """Live overdue verdict for one cadence-type payout_frequency ExtractedTerm.

    `latest_payout_date` and `days_since_last_payout` are the Contract's
    most recent observed Payout and how long ago that was, as of the moment
    `list_overdue_statuses` was called - not stored, recomputed every call.
    `expected_interval_days` is `term`'s stated cadence converted to days
    (`numeric_value * DAYS_PER_UNIT[unit]`). `is_overdue` is `True` exactly
    when `days_since_last_payout` exceeds `expected_interval_days` inflated
    by `settings.CADENCE_MISMATCH_TOLERANCE_RATIO` - the same tolerance
    knob `services._evaluate_cadence_term` already uses for the persisted
    cadence_mismatch comparison, reused rather than a second setting.
    """

    term_id: uuid.UUID
    is_overdue: bool
    days_since_last_payout: int
    expected_interval_days: float
    latest_payout_date: datetime


def list_overdue_statuses(*, contract: Contract) -> list[OverdueStatus]:
    """Live-compute overdue status for each of a Contract's cadence terms.

    Scope: only Payout-referenced Contracts (`razorpay_reference_type ==
    PAYOUT`), and only `payout_frequency` ExtractedTerm rows that are
    cadence-shaped (`is_cadence_term`, reusing the exact same classification
    services.py's persisted cross-check uses). A Subscription-referenced
    Contract, and an amount-shaped payout_frequency term on a Payout
    Contract, are both explicit non-goals - returns `[]` for either rather
    than attempting a comparison that has no meaningful "overdue" concept
    (a Subscription is diffed by exact config field, not empirical cadence;
    an amount term has no interval to be late against).

    Returns `[]` (not applicable) when the Contract has zero Payout
    PlatformRecords - that "no evidence at all" case is already covered by
    `missing_platform_evidence` at analysis time (stage 4); this live check
    must not duplicate or conflict with that persisted verdict by fabricating
    an overdue/not-overdue answer with nothing to measure from.

    A Contract can have more than one qualifying term (more than one
    payment-schedule clause, or more than one cadence term within one
    clause) - each is evaluated independently against the same observed
    Payout history and gets its own `OverdueStatus` entry, so this returns
    a list rather than a single optional result.

    Issues zero Razorpay API calls - reads only already-persisted
    ExtractedTerm and PlatformRecord rows, so this is fully exercised
    without `ENABLE_STAGE_4` or real Razorpay keys.
    """
    if contract.razorpay_reference_type != RazorpayReferenceType.PAYOUT:
        return []

    payout_records = list(
        get_platform_records_for_contract(
            contract=contract, record_type=PlatformRecordType.PAYOUT
        )
    )
    if not payout_records:
        return []

    latest_payout_date = max(record.razorpay_created_at for record in payout_records)
    days_since_last_payout = (django_timezone.now() - latest_payout_date).days

    statuses: list[OverdueStatus] = []
    for clause in contracts_selectors.list_clauses_for_contract(contract=contract):
        for term in pipeline_selectors.list_extracted_terms_for_clause(clause=clause):
            if term.term_type != TermType.PAYOUT_FREQUENCY.value or not is_cadence_term(term):
                continue

            numeric_value = term_numeric_value(term)
            unit = term_unit(term)
            if numeric_value is None or unit is None or unit not in DAYS_PER_UNIT:
                continue  # pragma: no cover - is_cadence_term already guarantees this

            expected_interval_days = numeric_value * DAYS_PER_UNIT[unit]
            is_overdue = days_since_last_payout > expected_interval_days * (
                1 + settings.CADENCE_MISMATCH_TOLERANCE_RATIO
            )
            statuses.append(
                OverdueStatus(
                    term_id=term.id,
                    is_overdue=is_overdue,
                    days_since_last_payout=days_since_last_payout,
                    expected_interval_days=expected_interval_days,
                    latest_payout_date=latest_payout_date,
                )
            )
    return statuses
