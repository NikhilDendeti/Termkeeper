"""Write-path service functions for the `razorpay_integration` app.

This app implements pipeline stage 4: cross-checking phase 1's
`ExtractedTerm` rows against real Razorpay platform evidence. Every write
(`PlatformRecord`, `MismatchFlag`, `AuditLogEntry`) goes through a function
here. `detect_mismatches` reads its inputs via selectors (this app's own,
`contracts.selectors`, and `pipeline.selectors`), never via an in-process
value handed from an earlier pipeline stage - the same no-in-memory-handoff
rule phase 1 established for stages 1-3. See design.md
(add-razorpay-crosscheck) - Context and Decisions.

Mismatch *existence* and *type* are always decided by deterministic code
comparison before any LLM call - `core.llm_client` is used only to
generate a quote-grounded human-readable `description` for an
already-decided cadence_mismatch/amount_mismatch, never to decide whether a
mismatch exists. See
specs/razorpay-integration/mismatch-flagging/spec.md (Requirement:
Deterministic mismatch classification precedes any LLM involvement).
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_timezone

from contracts import selectors as contracts_selectors
from contracts.models import Clause, Contract, RazorpayReferenceType
from core import llm_client
from pipeline import selectors as pipeline_selectors
from pipeline.models import AuditLogEntry, ExtractedTerm, TermType
from razorpay_integration import selectors as razorpay_selectors
from razorpay_integration.client import RazorpayConnector
from razorpay_integration.models import (
    MismatchFlag,
    MismatchType,
    PlatformRecord,
    PlatformRecordType,
)

# AuditLogEntry.stage is an unconstrained PositiveSmallIntegerField (choices
# are not DB-enforced) - stage 4 is additive by construction and requires no
# change to pipeline.models.PipelineStage (which only defines stages 1-3).
# See proposal.md - Impact.
_STAGE_4 = 4

# ---------------------------------------------------------------------------
# Term-type <-> platform-field mapping heuristics
# ---------------------------------------------------------------------------
#
# Phase 1's fixed TermType taxonomy (payout_frequency, milestone_trigger,
# penalty_amount, notice_period, auto_renewal_term) has no separate "payout
# amount" term type - `payout_frequency` is the only term type this app
# compares against platform data on either cross-check path, per
# proposal.md ("compare against ExtractedTerm.value_structured for
# payout_frequency terms - flagging cadence_mismatch, amount_mismatch, or
# missing_platform_evidence"). A payout_frequency term's `value_structured`
# is always a single {numeric_value, unit} pair, so this module classifies
# each such term as either a *cadence* term (its `unit` names a recognized
# time unit) or an *amount* term (any other unit, including none) - see
# `_is_cadence_term` / `_is_amount_term`. Every other term_type has no
# independently GET-able Subscription/Token equivalent and is always
# trigger_condition_unverifiable on the subscription path (task 5.3's
# milestone_trigger example generalizes to the whole rest of the taxonomy).

_TIME_UNITS: frozenset[str] = frozenset(
    {"day", "days", "week", "weeks", "month", "months", "year", "years"}
)
_DAYS_PER_UNIT: dict[str, float] = {
    "day": 1.0,
    "days": 1.0,
    "week": 7.0,
    "weeks": 7.0,
    "month": 30.0,
    "months": 30.0,
    "year": 365.0,
    "years": 365.0,
}
_PERIOD_BY_UNIT: dict[str, str] = {
    "day": "daily",
    "days": "daily",
    "week": "weekly",
    "weeks": "weekly",
    "month": "monthly",
    "months": "monthly",
    "year": "yearly",
    "years": "yearly",
}


def _term_unit(term: ExtractedTerm) -> str | None:
    value_structured = term.value_structured or {}
    unit = value_structured.get("unit")
    if isinstance(unit, str) and unit.strip():
        return unit.strip().lower()
    return None


def _term_numeric_value(term: ExtractedTerm) -> float | None:
    value_structured = term.value_structured or {}
    numeric_value = value_structured.get("numeric_value")
    if numeric_value is None:
        return None
    return float(numeric_value)


def _is_cadence_term(term: ExtractedTerm) -> bool:
    """Whether a payout_frequency term states a time interval (vs an amount)."""
    unit = _term_unit(term)
    return unit is not None and unit in _TIME_UNITS


def _is_amount_term(term: ExtractedTerm) -> bool:
    """Whether a payout_frequency term states a numeric amount (vs a cadence)."""
    return _term_numeric_value(term) is not None and not _is_cadence_term(term)


# ---------------------------------------------------------------------------
# Razorpay payload parsing helpers
# ---------------------------------------------------------------------------


def _parse_razorpay_timestamp(value: Any) -> datetime:
    """Razorpay entities carry `created_at` as a Unix epoch integer (seconds)."""
    if value is None:
        return django_timezone.now()
    return datetime.fromtimestamp(float(value), tz=UTC)


def _amount_to_major_units(amount_paise: Any) -> float:
    """Razorpay amounts are always expressed in paise (the smallest currency unit)."""
    if amount_paise is None:
        return 0.0
    return float(amount_paise) / 100.0


def _major_units_to_paise(amount: float) -> int:
    return int(round(Decimal(str(amount)) * 100))


# ---------------------------------------------------------------------------
# Primary path: payout-history fetch + empirical cadence/amount
# ---------------------------------------------------------------------------


def fetch_payout_history(*, contract: Contract) -> list[PlatformRecord]:
    """Fetch RazorpayX Payout history for `contract` via GET and persist it.

    No-ops (no GET call, no PlatformRecord) for a Contract whose
    razorpay_reference_type is not `payout` - its razorpay_reference_id
    would not be a fund_account_id. See
    specs/razorpay-integration/payout-history-crosscheck/spec.md.
    """
    if contract.razorpay_reference_type != RazorpayReferenceType.PAYOUT:
        return []

    connector = RazorpayConnector()
    response = connector.fetch_payouts(fund_account_id=contract.razorpay_reference_id)
    items = response.get("items", []) if isinstance(response, dict) else []

    records: list[PlatformRecord] = []
    with transaction.atomic():
        for item in items:
            records.append(
                PlatformRecord.objects.create(
                    contract=contract,
                    record_type=PlatformRecordType.PAYOUT.value,
                    razorpay_id=str(item.get("id", "")),
                    payload=item,
                    razorpay_created_at=_parse_razorpay_timestamp(item.get("created_at")),
                )
            )
    return records


def _compute_empirical_cadence_days(records: list[PlatformRecord]) -> float:
    """Median of consecutive created_at deltas (in days), ordered by time.

    Median (not mean) is deliberately outlier-resistant - see design.md -
    Risks ("Median-based cadence can still be skewed by a single very early
    or very late payout").
    """
    ordered = sorted(records, key=lambda record: record.razorpay_created_at)
    deltas_days = [
        (ordered[i].razorpay_created_at - ordered[i - 1].razorpay_created_at).total_seconds()
        / 86400.0
        for i in range(1, len(ordered))
    ]
    return statistics.median(deltas_days)


def _compute_empirical_amount(records: list[PlatformRecord]) -> float:
    """Median of Payout amounts, converted from paise to major currency units."""
    amounts = [_amount_to_major_units(record.payload.get("amount")) for record in records]
    return statistics.median(amounts)


def _latest_record(records: list[PlatformRecord]) -> PlatformRecord:
    return max(records, key=lambda record: record.razorpay_created_at)


def _deviation_ratio(*, expected: float, actual: float) -> float:
    if expected == 0:
        return 0.0 if actual == 0 else float("inf")
    return abs(actual - expected) / abs(expected)


def _list_payout_frequency_terms(*, contract: Contract) -> list[ExtractedTerm]:
    terms: list[ExtractedTerm] = []
    for clause in contracts_selectors.list_clauses_for_contract(contract=contract):
        for term in pipeline_selectors.list_extracted_terms_for_clause(clause=clause):
            if term.term_type == TermType.PAYOUT_FREQUENCY.value:
                terms.append(term)
    return terms


def _run_payout_crosscheck(*, contract: Contract) -> list[MismatchFlag]:
    """Cross-check a Contract's payout_frequency terms against Payout history."""
    payout_terms = _list_payout_frequency_terms(contract=contract)
    comparable_terms = [
        term for term in payout_terms if _is_cadence_term(term) or _is_amount_term(term)
    ]

    payout_records = list(
        razorpay_selectors.get_platform_records_for_contract(
            contract=contract, record_type=PlatformRecordType.PAYOUT.value
        )
    )

    if len(payout_records) < 2:
        return [
            _create_missing_platform_evidence_flag(
                extracted_term=term, payout_record_count=len(payout_records)
            )
            for term in comparable_terms
        ]

    empirical_cadence_days = _compute_empirical_cadence_days(payout_records)
    empirical_amount = _compute_empirical_amount(payout_records)
    representative_record = _latest_record(payout_records)

    flags: list[MismatchFlag] = []
    for term in comparable_terms:
        flag: MismatchFlag | None
        if _is_cadence_term(term):
            flag = _evaluate_cadence_term(
                term=term,
                empirical_cadence_days=empirical_cadence_days,
                platform_record=representative_record,
            )
        else:
            flag = _evaluate_amount_term(
                term=term,
                empirical_amount=empirical_amount,
                platform_record=representative_record,
            )
        if flag is not None:
            flags.append(flag)
    return flags


def _evaluate_cadence_term(
    *, term: ExtractedTerm, empirical_cadence_days: float, platform_record: PlatformRecord
) -> MismatchFlag | None:
    numeric_value = _term_numeric_value(term)
    unit = _term_unit(term)
    if numeric_value is None or unit is None or unit not in _DAYS_PER_UNIT:
        return None

    expected_days = numeric_value * _DAYS_PER_UNIT[unit]
    deviation_ratio = _deviation_ratio(expected=expected_days, actual=empirical_cadence_days)
    if deviation_ratio <= settings.CADENCE_MISMATCH_TOLERANCE_RATIO:
        return None

    expected_value = {"numeric_value": numeric_value, "unit": unit}
    actual_value = {"empirical_cadence_days": round(empirical_cadence_days, 2)}
    return _create_llm_described_mismatch_flag(
        mismatch_type=MismatchType.CADENCE_MISMATCH.value,
        extracted_term=term,
        platform_record=platform_record,
        expected_value=expected_value,
        actual_value=actual_value,
    )


def _evaluate_amount_term(
    *, term: ExtractedTerm, empirical_amount: float, platform_record: PlatformRecord
) -> MismatchFlag | None:
    numeric_value = _term_numeric_value(term)
    if numeric_value is None:
        return None

    deviation_ratio = _deviation_ratio(expected=numeric_value, actual=empirical_amount)
    if deviation_ratio <= settings.AMOUNT_MISMATCH_TOLERANCE_PCT:
        return None

    expected_value = {"numeric_value": numeric_value, "unit": _term_unit(term)}
    actual_value = {"empirical_amount": round(empirical_amount, 2)}
    return _create_llm_described_mismatch_flag(
        mismatch_type=MismatchType.AMOUNT_MISMATCH.value,
        extracted_term=term,
        platform_record=platform_record,
        expected_value=expected_value,
        actual_value=actual_value,
    )


# ---------------------------------------------------------------------------
# Secondary path: Subscription + Token config fetch and exact-field diff
# ---------------------------------------------------------------------------


def fetch_subscription_config(*, contract: Contract) -> list[PlatformRecord]:
    """Fetch Subscription + Token config for `contract` via GET and persist it.

    No-ops for a Contract whose razorpay_reference_type is not
    `subscription` - see
    specs/razorpay-integration/subscription-crosscheck/spec.md (Requirement:
    Secondary path restricted to subscription-referenced contracts).
    """
    if contract.razorpay_reference_type != RazorpayReferenceType.SUBSCRIPTION:
        return []

    connector = RazorpayConnector()
    subscription_payload = connector.fetch_subscription(
        subscription_id=contract.razorpay_reference_id
    )
    if not isinstance(subscription_payload, dict) or not subscription_payload.get("id"):
        return []

    records: list[PlatformRecord] = [
        PlatformRecord.objects.create(
            contract=contract,
            record_type=PlatformRecordType.SUBSCRIPTION.value,
            razorpay_id=str(subscription_payload.get("id", "")),
            payload=subscription_payload,
            razorpay_created_at=_parse_razorpay_timestamp(subscription_payload.get("created_at")),
        )
    ]

    customer_id = subscription_payload.get("customer_id")
    if customer_id:
        token_response = connector.fetch_token(customer_id=customer_id)
        token_items = token_response.get("items", []) if isinstance(token_response, dict) else []
        active_token = _select_active_token(token_items)
        if active_token is not None:
            records.append(
                PlatformRecord.objects.create(
                    contract=contract,
                    record_type=PlatformRecordType.TOKEN.value,
                    razorpay_id=str(active_token.get("id", "")),
                    payload=active_token,
                    razorpay_created_at=_parse_razorpay_timestamp(active_token.get("created_at")),
                )
            )
    return records


def _select_active_token(token_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the freshest non-cancelled Token from a customer's token list.

    UPI Autopay tokens cannot be PATCHed - a renegotiated mandate is
    modeled as cancel+recreate, which can leave multiple Token
    PlatformRecords under one logical mandate. The token diffed against is
    always the one with the latest `created_at` that is not cancelled -
    see design.md - Risks.
    """
    candidates = [item for item in token_items if item.get("status") != "cancelled"]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.get("created_at") or 0)


def _list_all_terms(*, contract: Contract) -> list[ExtractedTerm]:
    terms: list[ExtractedTerm] = []
    for clause in contracts_selectors.list_clauses_for_contract(contract=contract):
        terms.extend(pipeline_selectors.list_extracted_terms_for_clause(clause=clause))
    return terms


def _run_subscription_crosscheck(*, contract: Contract) -> list[MismatchFlag]:
    """Cross-check a Contract's extracted terms against Subscription/Token fields."""
    subscription_record = (
        razorpay_selectors.get_platform_records_for_contract(
            contract=contract, record_type=PlatformRecordType.SUBSCRIPTION.value
        )
        .order_by("-razorpay_created_at")
        .first()
    )

    flags: list[MismatchFlag] = []
    for term in _list_all_terms(contract=contract):
        if term.term_type != TermType.PAYOUT_FREQUENCY.value:
            flags.append(_create_trigger_condition_unverifiable_flag(extracted_term=term))
            continue

        if subscription_record is None:
            continue  # nothing fetched to diff against

        flag: MismatchFlag | None
        if _is_cadence_term(term):
            flag = _evaluate_subscription_cadence_term(
                term=term, subscription_record=subscription_record
            )
        elif _is_amount_term(term):
            flag = _evaluate_subscription_amount_term(
                term=term, subscription_record=subscription_record
            )
        else:
            flag = None  # qualitative payout_frequency term, no number to diff

        if flag is not None:
            flags.append(flag)

    return flags


def _evaluate_subscription_cadence_term(
    *, term: ExtractedTerm, subscription_record: PlatformRecord
) -> MismatchFlag | None:
    numeric_value = _term_numeric_value(term)
    unit = _term_unit(term)
    if numeric_value is None or unit is None or unit not in _PERIOD_BY_UNIT:
        return None

    expected_period = _PERIOD_BY_UNIT[unit]
    expected_interval = numeric_value

    payload = subscription_record.payload
    actual_period = payload.get("period")
    actual_interval = payload.get("interval")

    matches = (
        actual_period == expected_period
        and actual_interval is not None
        and float(actual_interval) == float(expected_interval)
    )
    if matches:
        return None

    expected_value = {"period": expected_period, "interval": expected_interval}
    actual_value = {"period": actual_period, "interval": actual_interval}
    return _create_llm_described_mismatch_flag(
        mismatch_type=MismatchType.CADENCE_MISMATCH.value,
        extracted_term=term,
        platform_record=subscription_record,
        expected_value=expected_value,
        actual_value=actual_value,
    )


def _evaluate_subscription_amount_term(
    *, term: ExtractedTerm, subscription_record: PlatformRecord
) -> MismatchFlag | None:
    numeric_value = _term_numeric_value(term)
    if numeric_value is None:
        return None

    payload = subscription_record.payload
    item = payload.get("item") or {}
    actual_amount_paise = item.get("amount")

    expected_paise = _major_units_to_paise(numeric_value)
    matches = actual_amount_paise is not None and int(actual_amount_paise) == expected_paise
    if matches:
        return None

    expected_value = {"numeric_value": numeric_value, "unit": _term_unit(term)}
    actual_value = {"item_amount_paise": actual_amount_paise}
    return _create_llm_described_mismatch_flag(
        mismatch_type=MismatchType.AMOUNT_MISMATCH.value,
        extracted_term=term,
        platform_record=subscription_record,
        expected_value=expected_value,
        actual_value=actual_value,
    )


# ---------------------------------------------------------------------------
# Mismatch persistence and quote-grounded description generation
# ---------------------------------------------------------------------------

_MISMATCH_DESCRIPTION_PROMPT_VERSION = "mismatch-description-v1"
_MISMATCH_DESCRIPTION_MAX_ATTEMPTS = 2

_MISMATCH_DESCRIPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "expected_quote": {"type": "string"},
        "actual_quote": {"type": "string"},
    },
    "required": ["description", "expected_quote", "actual_quote"],
    "additionalProperties": False,
}

_MISMATCH_DESCRIPTION_SYSTEM_PROMPT = (
    "You write a one- or two-sentence description of a detected mismatch "
    "between a contract-stated payment term and what was actually observed "
    "on the Razorpay payment rail. `expected_quote` MUST be an exact, "
    "character-for-character quote drawn from the contract text given as "
    "the expected-value source. `actual_quote` MUST be an exact, "
    "character-for-character quote drawn from the platform-data text given "
    "as the actual-value source - quote the JSON text itself, do not "
    "paraphrase it. Never claim that a payout schedule configuration was "
    "retrieved from or exists on the Payouts side - Razorpay exposes no "
    "such queryable setting; describe payout-side evidence only as "
    "observed or empirical Payout history."
)


def _create_llm_described_mismatch_flag(
    *,
    mismatch_type: str,
    extracted_term: ExtractedTerm,
    platform_record: PlatformRecord,
    expected_value: dict[str, Any],
    actual_value: dict[str, Any],
) -> MismatchFlag:
    """Persist a cadence_mismatch/amount_mismatch MismatchFlag.

    The decision that a mismatch exists, and its mismatch_type, has already
    been made deterministically by the caller before this function runs -
    only the human-readable `description` is generated via
    `core.llm_client`. See
    specs/razorpay-integration/mismatch-flagging/spec.md (Requirement:
    Deterministic mismatch classification precedes any LLM involvement).
    """
    description = _generate_mismatch_description(
        contract=extracted_term.clause.contract,
        clause=extracted_term.clause,
        mismatch_type=mismatch_type,
        extracted_term=extracted_term,
        platform_record=platform_record,
        expected_value=expected_value,
        actual_value=actual_value,
    )
    return MismatchFlag.objects.create(
        extracted_term=extracted_term,
        platform_record=platform_record,
        mismatch_type=mismatch_type,
        expected_value=expected_value,
        actual_value=actual_value,
        description=description,
    )


def _generate_mismatch_description(
    *,
    contract: Contract,
    clause: Clause,
    mismatch_type: str,
    extracted_term: ExtractedTerm,
    platform_record: PlatformRecord,
    expected_value: dict[str, Any],
    actual_value: dict[str, Any],
) -> str:
    """Generate a quote-grounded description, retrying once on failed verification.

    Both the expected-value quote (against the ExtractedTerm's `value_raw`)
    and the actual-value quote (against the PlatformRecord's stringified
    payload) are independently verified via `core.llm_client.quote_is_verbatim`
    before the description is trusted. If verification still fails after
    one retry, a deterministic templated description is used instead - see
    specs/razorpay-integration/mismatch-flagging/spec.md (Requirement:
    Quote-grounded description generation).
    """
    expected_source = extracted_term.value_raw
    actual_source = json.dumps(platform_record.payload, indent=2, ensure_ascii=False)
    user_content = (
        f"mismatch_type: {mismatch_type}\n\n"
        f"Expected-value source (contract clause text):\n{expected_source}\n\n"
        f"Actual-value source (raw Razorpay platform data):\n{actual_source}\n"
    )

    result: dict[str, Any] = {}
    total_latency_ms = 0
    verified = False
    for _attempt in range(_MISMATCH_DESCRIPTION_MAX_ATTEMPTS):
        started_at = time.monotonic()
        result = llm_client.get_structured_completion(
            _MISMATCH_DESCRIPTION_SYSTEM_PROMPT,
            user_content,
            _MISMATCH_DESCRIPTION_SCHEMA,
            prompt_version=_MISMATCH_DESCRIPTION_PROMPT_VERSION,
        )
        total_latency_ms += int((time.monotonic() - started_at) * 1000)

        expected_ok = llm_client.quote_is_verbatim(expected_source, result["expected_quote"])
        actual_ok = llm_client.quote_is_verbatim(actual_source, result["actual_quote"])
        if expected_ok and actual_ok:
            verified = True
            break

    _create_audit_log_entry(
        contract=contract,
        clause=clause,
        llm_response_raw=result,
        latency_ms=total_latency_ms,
    )

    if verified:
        return str(result["description"])
    return _deterministic_template_description(
        mismatch_type=mismatch_type, expected_value=expected_value, actual_value=actual_value
    )


def _deterministic_template_description(
    *, mismatch_type: str, expected_value: dict[str, Any], actual_value: dict[str, Any]
) -> str:
    """Templated fallback used when the LLM-generated quotes fail verification.

    Never uses the phrase "schedule config" (or an equivalent) - see
    specs/razorpay-integration/payout-history-crosscheck/spec.md
    (Requirement: No claim of a payout schedule configuration).
    """
    if mismatch_type == MismatchType.CADENCE_MISMATCH.value:
        return (
            f"Contract-stated cadence {expected_value} does not match the cadence "
            f"observed on the Razorpay payment rail {actual_value}."
        )
    if mismatch_type == MismatchType.AMOUNT_MISMATCH.value:
        return (
            f"Contract-stated amount {expected_value} does not match the amount "
            f"observed on the Razorpay payment rail {actual_value}."
        )
    # Unreachable via any code path that calls this function today (always
    # cadence_mismatch or amount_mismatch) - a defensive fallback only.
    return f"Mismatch detected: expected {expected_value}, observed {actual_value}."


def _create_missing_platform_evidence_flag(
    *, extracted_term: ExtractedTerm, payout_record_count: int
) -> MismatchFlag:
    """Persist a missing_platform_evidence MismatchFlag - no LLM call, no PlatformRecord.

    There is no platform-side text to ground a quote against when no (or
    only one) Payout record exists, so this description is always
    deterministic - see
    specs/razorpay-integration/mismatch-flagging/spec.md (scenario scoping
    quote-grounded generation to cadence_mismatch/amount_mismatch only).
    """
    description = (
        "Fewer than 2 Payout records were found in the observed Payout "
        f'history to cross-check the contract-stated term "{extracted_term.value_raw}" '
        f"(found {payout_record_count}); no empirical cadence or amount could be "
        "derived from Payout history."
    )
    return MismatchFlag.objects.create(
        extracted_term=extracted_term,
        platform_record=None,
        mismatch_type=MismatchType.MISSING_PLATFORM_EVIDENCE.value,
        expected_value=extracted_term.value_structured,
        actual_value={"payout_record_count": payout_record_count},
        description=description,
    )


def _create_trigger_condition_unverifiable_flag(*, extracted_term: ExtractedTerm) -> MismatchFlag:
    """Persist a trigger_condition_unverifiable MismatchFlag - no LLM call, no PlatformRecord."""
    description = (
        f'The contract-stated term "{extracted_term.value_raw}" '
        f"({extracted_term.get_term_type_display()}) has no corresponding "
        "independently GET-able Subscription or Token field on Razorpay, so it "
        "cannot be cross-checked against platform data."
    )
    return MismatchFlag.objects.create(
        extracted_term=extracted_term,
        platform_record=None,
        mismatch_type=MismatchType.TRIGGER_CONDITION_UNVERIFIABLE.value,
        expected_value=extracted_term.value_structured,
        actual_value={},
        description=description,
    )


def _create_audit_log_entry(
    *, contract: Contract, clause: Clause, llm_response_raw: dict[str, Any], latency_ms: int
) -> AuditLogEntry:
    """Persist the AuditLogEntry(stage=4) each description-generation call writes.

    Reuses phase 1's AuditLogEntry model verbatim - see task 6.4 and
    proposal.md - Impact ("AuditLogEntry.stage is already an unconstrained
    int, so stage=4 is additive by construction").
    """
    return AuditLogEntry.objects.create(
        contract=contract,
        clause=clause,
        stage=_STAGE_4,
        prompt_version=_MISMATCH_DESCRIPTION_PROMPT_VERSION,
        llm_response_raw=llm_response_raw,
        model_name=settings.OPENAI_MODEL,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# Stage-4 orchestration
# ---------------------------------------------------------------------------


def detect_mismatches(*, contract: Contract) -> list[MismatchFlag]:
    """Stage 4 orchestrator: branch on razorpay_reference_type, fetch evidence, cross-check.

    Called by `pipeline.services.run_pipeline` via a function-local import
    after stage 3 - see design.md "Extending run_pipeline without a
    circular import." Reads its own inputs via selectors rather than
    accepting pre-fetched ExtractedTerm objects, preserving phase 1's
    no-in-memory-handoff rule.
    """
    if contract.razorpay_reference_type == RazorpayReferenceType.PAYOUT:
        fetch_payout_history(contract=contract)
        return _run_payout_crosscheck(contract=contract)

    if contract.razorpay_reference_type == RazorpayReferenceType.SUBSCRIPTION:
        fetch_subscription_config(contract=contract)
        return _run_subscription_crosscheck(contract=contract)

    return []  # pragma: no cover - razorpay_reference_type has no other value
