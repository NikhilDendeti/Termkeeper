"""Read-path selector functions for the `reporting` app.

`reporting` owns no models - it only composes rows already owned by other
apps: RiskAssessment (`risk_scoring`), MismatchFlag (`razorpay_integration`),
and AuditLogEntry (`pipeline`). Every function here is a pure query-and-
compute function; nothing here writes to the database. See design.md
(add-risk-scoring-report) - Decisions ("Two new apps: risk_scoring (writes)
and reporting (reads only, no models)", "get_contract_report lives in
reporting/selectors.py, not services.py").

`get_contract_reasoning_chain` and `scan_razorpay_guardrail` (plus their
dataclasses and private helpers) were relocated here from
`report_ui/selectors.py` in add-react-frontend - see that change's
design.md ("Refactor: relocate the reasoning-chain and guardrail-scan reads
from report_ui.selectors to reporting.selectors"). `reporting` is this
project's designated read-model app and both `report_ui` (templates) and
this app's own new JSON endpoints need these reads; `reporting` must not
depend on `report_ui` (that would invert the established phase ordering -
`report_ui` depends on `reporting`, never the reverse). No behavior change
from the move - see the docstrings on each moved function for their
original rationale.
"""

from __future__ import annotations

import ast
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db.models import F, QuerySet

from contracts import selectors as contracts_selectors
from contracts.models import Clause, ClauseType, Contract, RazorpayReferenceType
from core.audit_hash import GENESIS_PREV_HASH, compute_entry_hash
from evaluation import selectors as evaluation_selectors
from pipeline import selectors as pipeline_selectors
from pipeline.models import AuditLogEntry, ExtractedTerm
from razorpay_integration import selectors as razorpay_selectors
from razorpay_integration.models import MismatchFlag, PlatformRecord, PlatformRecordType
from risk_scoring import selectors as risk_scoring_selectors
from risk_scoring.models import RiskAssessment, SeverityChoices

# Fixed severity -> weight mapping used only to compute the report's
# overall_risk_score - independent of risk_scoring's own severity *band*
# formula (which decides which of these labels a clause gets in the first
# place). See specs/reporting/aggregate-report/spec.md (Requirement: Fixed
# severity-to-weight mapping).
_SEVERITY_WEIGHTS: dict[str, float] = {
    SeverityChoices.CRITICAL.value: 1.0,
    SeverityChoices.HIGH.value: 0.75,
    SeverityChoices.MEDIUM.value: 0.5,
    SeverityChoices.LOW.value: 0.25,
}


def get_contract_report(*, contract: Contract) -> dict[str, Any]:
    """Aggregate a contract's persisted RiskAssessment/MismatchFlag rows into one report.

    Issues no call to the Claude API - every input is already persisted.
    needs_human_review RiskAssessments are excluded from
    `overall_risk_score`'s numerator and denominator and reported separately
    in `needs_human_review_clauses`, so a contract with zero scored clauses
    yields `overall_risk_score=None`, never `0`. See
    specs/reporting/aggregate-report/spec.md.

    `severity_breakdown_by_clause_type` groups that same `scored` list by
    `clause.clause_type` - count and mean asymmetry_score per group - and is
    an empty dict (never omitted or an error) when there are no scored
    clauses, mirroring `overall_risk_score=None` in that same case. See
    specs/reporting/clause-type-breakdown/spec.md.
    """
    assessments = list(
        risk_scoring_selectors.list_risk_assessments_for_contract(contract=contract)
    )

    scored = [a for a in assessments if a.severity != SeverityChoices.NEEDS_HUMAN_REVIEW.value]
    needs_review = [
        a for a in assessments if a.severity == SeverityChoices.NEEDS_HUMAN_REVIEW.value
    ]

    overall_risk_score = _compute_overall_risk_score(scored)

    ranked = sorted(
        scored,
        key=lambda a: (_SEVERITY_WEIGHTS[a.severity], abs(a.asymmetry_score)),
        reverse=True,
    )

    mismatches = razorpay_selectors.list_mismatch_flags_for_contract(
        contract=contract
    ).select_related("extracted_term__clause")

    return {
        "contract_id": contract.id,
        "overall_risk_score": overall_risk_score,
        "flagged_clauses": [_serialize_flagged_clause(a) for a in ranked],
        "platform_mismatches": [_serialize_mismatch(m) for m in mismatches],
        "needs_human_review_clauses": [_serialize_review_clause(a) for a in needs_review],
        "severity_breakdown_by_clause_type": _compute_clause_type_breakdown(scored),
    }


def get_full_audit_trail(*, contract: Contract) -> QuerySet[AuditLogEntry]:
    """Thin pass-through to `pipeline.selectors.get_audit_trail`.

    Kept here (rather than importing `pipeline.selectors` directly from the
    view and the CLI command) so both surfaces import from one place. See
    design.md - Decisions.
    """
    return pipeline_selectors.get_audit_trail(contract=contract)


# ---------------------------------------------------------------------------
# Audit-chain verification (spec: pipeline/audit-log-integrity)
# ---------------------------------------------------------------------------
#
# Mirrors `scan_razorpay_guardrail`'s dataclass-result, recompute-don't-trust
# pattern below: a frozen dataclass result, a `passed: bool`, live
# recomputation on every call, nothing cached or stored. See
# openspec/changes/add-audit-log-hash-chain/design.md ("The verification
# command").


@dataclass(frozen=True)
class AuditChainBreak:
    """One point where a Contract's persisted hash chain diverges from what
    recomputation from its own rows would produce."""

    contract_id: uuid.UUID
    entry_id: uuid.UUID
    chain_sequence: int
    reason: str  # "entry_hash_mismatch" | "prev_hash_mismatch" | "chain_sequence_gap"


@dataclass(frozen=True)
class AuditChainVerificationResult:
    """Result of one `verify_audit_chain` invocation.

    `passed` is `True` only when `breaks` is empty across every contract
    checked - exempt entries never affect `passed`. `entries_exempt` counts
    pre-existing (null `entry_hash`) rows, which are never included in
    `entries_verified` or `breaks` - see specs/pipeline/audit-log-integrity/
    spec.md (Requirement: Pre-existing entries are explicit chain-exempt,
    never silently counted as verified).
    """

    passed: bool
    contracts_checked: int
    entries_verified: int
    entries_exempt: int
    breaks: list[AuditChainBreak] = field(default_factory=list)


def verify_audit_chain(*, contract: Contract | None = None) -> AuditChainVerificationResult:
    """Recompute and verify the AuditLogEntry hash chain for one Contract, or all.

    Runs live against the current state of the persisted rows on every
    call - never cached or stored, mirroring `scan_razorpay_guardrail`. Each
    contract's chain is walked independently, in `chain_sequence` order
    (nulls last, so exempt rows sort after every hashed row and are never
    interleaved with the real chain) - see design.md (Decision 1): a break
    confined to one contract's chain is never reported against any other
    contract, and each contract's `chain_sequence` is expected to start at
    `1` independently. A null-`entry_hash` row is counted as exempt and
    skipped - never treated as a break and never treated as verified (see
    design.md - Decision 2). For each remaining (hashed) row, in order: its
    `chain_sequence` must equal the running expected sequence (gap-free,
    starting at `1` for the contract's first hashed entry - a gap is itself
    a break, since chain_sequence increments are the only thing standing
    between "entries deleted" and "entries missing"), its `prev_hash` must
    equal the previous hashed entry's `entry_hash` (or `GENESIS_PREV_HASH`
    for the first), and `core.audit_hash.compute_entry_hash(entry)` -
    exactly the function the writer used - must equal the entry's stored
    `entry_hash`. Any mismatch is one `AuditChainBreak`.
    """
    contracts = [contract] if contract is not None else list(contracts_selectors.list_contracts())

    entries_verified = 0
    entries_exempt = 0
    breaks: list[AuditChainBreak] = []

    for one_contract in contracts:
        entries = AuditLogEntry.objects.filter(contract=one_contract).order_by(
            F("chain_sequence").asc(nulls_last=True)
        )

        expected_sequence = 1
        previous_hash = GENESIS_PREV_HASH
        for entry in entries:
            if entry.entry_hash is None:
                entries_exempt += 1
                continue

            entries_verified += 1

            # `create_audit_log_entry` never persists entry_hash without
            # also persisting chain_sequence in the same transaction - a
            # null chain_sequence here means the row was tampered with
            # directly. 0 is a safe sentinel (a real chain_sequence always
            # starts at 1), so this still compares unequal to any
            # legitimate expected_sequence and is reported as a break below.
            actual_sequence = entry.chain_sequence if entry.chain_sequence is not None else 0

            if actual_sequence != expected_sequence:
                breaks.append(
                    AuditChainBreak(
                        contract_id=one_contract.id,
                        entry_id=entry.id,
                        chain_sequence=actual_sequence,
                        reason="chain_sequence_gap",
                    )
                )
            elif entry.prev_hash != previous_hash:
                breaks.append(
                    AuditChainBreak(
                        contract_id=one_contract.id,
                        entry_id=entry.id,
                        chain_sequence=actual_sequence,
                        reason="prev_hash_mismatch",
                    )
                )
            elif compute_entry_hash(entry) != entry.entry_hash:
                breaks.append(
                    AuditChainBreak(
                        contract_id=one_contract.id,
                        entry_id=entry.id,
                        chain_sequence=actual_sequence,
                        reason="entry_hash_mismatch",
                    )
                )

            expected_sequence = actual_sequence + 1
            previous_hash = entry.entry_hash

    return AuditChainVerificationResult(
        passed=not breaks,
        contracts_checked=len(contracts),
        entries_verified=entries_verified,
        entries_exempt=entries_exempt,
        breaks=breaks,
    )


# ---------------------------------------------------------------------------
# Contract summaries (spec: api/contract-listing)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractSummary:
    """Headline summary of one Contract, enough to render a dashboard list row.

    `overall_risk_score` and `needs_human_review_count` are read straight off
    `get_contract_report` (never re-derived), so a summary always reflects
    the same aggregate-report behavior as the full report endpoint -
    including `overall_risk_score` being `None`, not a fabricated value,
    when a Contract has no scored clauses yet. See
    specs/api/contract-listing/spec.md (Requirement: Summary reflects
    current pipeline state).
    """

    contract_id: uuid.UUID
    engagement_id: str
    razorpay_reference_type: str
    overall_risk_score: float | None
    needs_human_review_count: int
    created_at: datetime


def list_contract_summaries() -> list[ContractSummary]:
    """Build one summary per ingested Contract, newest-created first.

    Thin composition of `contracts.selectors.list_contracts` (ordering) and
    `get_contract_report` (per-contract aggregate) - no read logic is
    re-derived here. See specs/api/contract-listing/spec.md (Requirement:
    Contract list endpoint).

    Excludes synthetic evaluation-dataset fixture Contracts (see
    `evaluation.selectors.list_eval_fixture_contract_ids`) - those are
    internal ground-truth data for `manage.py eval run`, never run through
    the real pipeline until scored, so they would otherwise show up
    permanently "not yet classified" and confuse a reader of the real
    contract dashboard, including a partially-generated dataset left behind
    by an interrupted `eval generate-dataset` run.
    """
    fixture_ids = evaluation_selectors.list_eval_fixture_contract_ids()
    summaries: list[ContractSummary] = []
    for contract in contracts_selectors.list_contracts():
        if contract.id in fixture_ids:
            continue
        report = get_contract_report(contract=contract)
        summaries.append(
            ContractSummary(
                contract_id=contract.id,
                engagement_id=contract.engagement_id,
                razorpay_reference_type=contract.razorpay_reference_type,
                overall_risk_score=report["overall_risk_score"],
                needs_human_review_count=len(report["needs_human_review_clauses"]),
                created_at=contract.created_at,
            )
        )
    return summaries


# ---------------------------------------------------------------------------
# Contract document (the original submitted text, not yet exposed anywhere -
# every other endpoint returns segmented clauses or aggregates, never the
# whole document a person could actually read end to end)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractDocument:
    """A Contract's own fields, including its full raw_text.

    Every other read in this app returns segmented clauses or aggregated
    scores - nothing exposes the original document a human submitted, so a
    viewer has no way to read the whole contract as written. This closes
    that gap with a direct, unaggregated read of the Contract row itself.

    `needs_human_review` and `human_review_reason` mirror the Contract-level
    fields `contracts.services.mark_contract_needs_human_review` sets when
    stage-1 segmentation fails verbatim-matching twice - previously set on
    the model but never read back out through any selector or serializer,
    so a flagged contract's viewer had no way to see why. `human_review_reason`
    is `None` whenever `needs_human_review` is `False` (the model's own
    default state - never set together).
    """

    contract_id: uuid.UUID
    engagement_id: str
    razorpay_reference_type: str
    razorpay_reference_id: str
    raw_text: str
    source_filename: str | None
    created_at: datetime
    needs_human_review: bool
    human_review_reason: str | None


def get_contract_document(*, contract: Contract) -> ContractDocument:
    """Return a Contract's own fields, including its full raw_text, unaggregated."""
    return ContractDocument(
        contract_id=contract.id,
        engagement_id=contract.engagement_id,
        razorpay_reference_type=contract.razorpay_reference_type,
        razorpay_reference_id=contract.razorpay_reference_id,
        raw_text=contract.raw_text,
        source_filename=contract.source_filename,
        created_at=contract.created_at,
        needs_human_review=contract.needs_human_review,
        human_review_reason=contract.human_review_reason,
    )


# ---------------------------------------------------------------------------
# Reasoning-chain assembly (spec: api/reasoning-chain; report-ui/reasoning-chain-view)
# ---------------------------------------------------------------------------
#
# Relocated from `report_ui/selectors.py` (add-react-frontend) - see the
# module docstring above. `report_ui`'s reasoning-chain view and this app's
# `ContractReasoningChainAPIView` both call `get_contract_reasoning_chain`;
# neither re-derives the join.
#
# design.md (add-report-ui)'s forward-reference assumption named a single
# `risk_scoring.selectors.get_contract_report` aggregate the reasoning-chain
# view would call directly; the selector actually written for phase 3
# (`get_contract_report`, above) only aggregates *scored* clauses, omitting
# any clause that never reached stage 5 - insufficient for
# specs/report-ui/reasoning-chain-view/spec.md's "no clause omitted"
# requirement. This function closes that gap by joining `contracts`,
# `pipeline`, and `risk_scoring`'s own per-clause selectors instead of
# re-deriving their queries.


@dataclass(frozen=True)
class ClauseReasoningChain:
    """One clause's full reasoning chain: classification through risk verdict.

    `classification_needs_human_review` mirrors
    `clause.clause_type == ClauseType.NEEDS_HUMAN_REVIEW` - hoisted onto its
    own field so callers never have to compare against the raw taxonomy
    string. `mismatch_flags` is this clause's platform evidence - every
    MismatchFlag reachable from the clause via its ExtractedTerm rows
    (empty when no platform evidence exists for this clause, per
    specs/api/reasoning-chain/spec.md - "Clause with no platform evidence").
    `verified_platform_records` is this clause's *confirmed* platform
    evidence - the contract's relevant PlatformRecords, populated only when
    the clause has at least one ExtractedTerm, has zero `mismatch_flags`,
    and the contract actually has relevant PlatformRecord data to show;
    empty otherwise, including when the clause was never checked at all.
    See specs/reporting/confirmed-platform-evidence/spec.md
    (add-confirmed-platform-evidence). `risk_assessment` is `None` when
    stage 5 has not yet run for this clause (specs/api/reasoning-chain/spec.md
    - "Clause not yet risk-scored").
    """

    clause: Clause
    classification_needs_human_review: bool
    extracted_terms: list[ExtractedTerm]
    mismatch_flags: list[MismatchFlag]
    verified_platform_records: list[PlatformRecord]
    risk_assessment: RiskAssessment | None


def get_contract_reasoning_chain(*, contract: Contract) -> list[ClauseReasoningChain]:
    """Build the full per-clause reasoning chain for a contract, in sequence order.

    Every clause is included regardless of `clause_type` or review state -
    see specs/api/reasoning-chain/spec.md (Requirement: Reasoning-chain
    endpoint - "Every clause included regardless of state").
    """
    chains: list[ClauseReasoningChain] = []
    for clause in contracts_selectors.list_clauses_for_contract(contract=contract):
        extracted_terms = list(pipeline_selectors.list_extracted_terms_for_clause(clause=clause))
        mismatch_flags = list(risk_scoring_selectors.get_linked_mismatch_flags(clause=clause))
        verified_platform_records = _get_verified_platform_records(
            contract=contract, extracted_terms=extracted_terms, mismatch_flags=mismatch_flags
        )
        risk_assessment = risk_scoring_selectors.get_risk_assessment_for_clause(clause=clause)
        chains.append(
            ClauseReasoningChain(
                clause=clause,
                classification_needs_human_review=(
                    clause.clause_type == ClauseType.NEEDS_HUMAN_REVIEW.value
                ),
                extracted_terms=extracted_terms,
                mismatch_flags=mismatch_flags,
                verified_platform_records=verified_platform_records,
                risk_assessment=risk_assessment,
            )
        )
    return chains


def _get_verified_platform_records(
    *,
    contract: Contract,
    extracted_terms: list[ExtractedTerm],
    mismatch_flags: list[MismatchFlag],
) -> list[PlatformRecord]:
    """The contract's relevant PlatformRecords, when this clause is a confirmed match.

    Populated only when the clause has at least one ExtractedTerm and zero
    linked MismatchFlags - a mismatch always takes precedence (empty
    confirmed evidence), and a clause with nothing extracted was never
    checked in the first place. See design.md (add-confirmed-platform-
    evidence) - Decisions, and
    specs/reporting/confirmed-platform-evidence/spec.md.

    "Relevant" mirrors the branch `razorpay_integration.services.
    detect_mismatches` itself uses: payout records for a payout-referenced
    contract, both subscription and token records for a subscription-
    referenced one (a subscription-referenced contract's configured mandate
    can be evidenced by either).
    """
    if not extracted_terms or mismatch_flags:
        return []

    if contract.razorpay_reference_type == RazorpayReferenceType.PAYOUT.value:
        return list(
            razorpay_selectors.get_platform_records_for_contract(
                contract=contract, record_type=PlatformRecordType.PAYOUT
            )
        )

    subscription_records = list(
        razorpay_selectors.get_platform_records_for_contract(
            contract=contract, record_type=PlatformRecordType.SUBSCRIPTION
        )
    )
    token_records = list(
        razorpay_selectors.get_platform_records_for_contract(
            contract=contract, record_type=PlatformRecordType.TOKEN
        )
    )
    return subscription_records + token_records


# ---------------------------------------------------------------------------
# Guardrail scan (spec: api/guardrail-verification; report-ui/guardrail-verification-view)
# ---------------------------------------------------------------------------
#
# Relocated from `report_ui/selectors.py` (add-react-frontend) - see the
# module docstring above. Statically scans `razorpay_integration`'s
# production-path source files for HTTP/SDK write calls. Parses source text
# with `ast` only - it never imports or executes the scanned modules, so the
# scan itself can never issue a network call.

# `razorpay_integration`'s production-path modules - the only files
# `detect_mismatches` (pipeline stage 4) ever reaches. See
# razorpay_integration/client.py and razorpay_integration/services.py module
# docstrings.
_DEFAULT_SCANNED_PATHS: tuple[Path, ...] = (
    Path(settings.BASE_DIR) / "razorpay_integration" / "client.py",
    Path(settings.BASE_DIR) / "razorpay_integration" / "services.py",
)

# The one module in this project that legitimately issues write calls
# against Razorpay - test-mode fixture/demo-seeding code, never imported by
# the production path. See razorpay_integration/fixtures.py module
# docstring and razorpay_integration/tests/test_fixtures_isolation.py.
_DEFAULT_EXCLUDED_PATHS: tuple[Path, ...] = (
    Path(settings.BASE_DIR) / "razorpay_integration" / "fixtures.py",
)

# Any call to a method with one of these names is an HTTP write verb
# against a live resource - mirrors
# razorpay_integration/tests/test_client.py::_FORBIDDEN_VERB_METHOD_NAMES,
# the dynamic guardrail test already enforcing this on the production path.
_WRITE_VERB_METHOD_NAMES: frozenset[str] = frozenset(
    {"post", "put", "patch", "delete", "post_url", "put_url", "patch_url", "delete_url"}
)

# Known razorpay-SDK resource methods that mutate a live resource without
# using one of the generic verb names above (e.g. `sdk_client.subscription.
# create(...)`) - see razorpay_integration/fixtures.py for the only place
# these are legitimately called. Matched against the full dotted call
# target, not just the trailing attribute name, so a same-named but
# unrelated method (e.g. a local queryset `.create(...)`) is never
# false-flagged.
_KNOWN_SDK_WRITE_CALL_TARGETS: frozenset[str] = frozenset(
    {
        "sdk_client.subscription.create",
        "sdk_client.token.create",
        "client.subscription.create",
        "client.token.create",
    }
)


@dataclass(frozen=True)
class GuardrailViolation:
    """One write-call match found by `scan_razorpay_guardrail`."""

    file: str
    line: int
    matched_call: str


@dataclass(frozen=True)
class GuardrailScanResult:
    """Result of one `scan_razorpay_guardrail` invocation.

    `passed` is `True` only when `violations` is empty across every file in
    `scanned_files` - see specs/api/guardrail-verification/spec.md
    (Requirement: Guardrail-verification endpoint).
    """

    passed: bool
    scanned_files: list[str] = field(default_factory=list)
    violations: list[GuardrailViolation] = field(default_factory=list)


def scan_razorpay_guardrail(
    *,
    scanned_paths: tuple[Path, ...] | None = None,
    excluded_paths: tuple[Path, ...] | None = None,
) -> GuardrailScanResult:
    """Statically scan `razorpay_integration`'s production path for write calls.

    Runs live against the current state of the source files on every call -
    never cached or stored - see specs/api/guardrail-verification/spec.md
    (Scenario: Result reflects current source, not a cached claim). Parses
    each file with `ast.parse` and walks `ast.Call` nodes; never imports or
    executes a scanned module, so the scan itself issues no network call.

    `excluded_paths` is subtracted from `scanned_paths` (defaults: exclude
    `razorpay_integration/fixtures.py` from the two production-path files)
    so a caller can prove the exclusion is active - not merely that the
    default list happens not to include it - by passing a `scanned_paths`
    tuple that includes an excluded file and asserting it never appears in
    the result.
    """
    paths = scanned_paths if scanned_paths is not None else _DEFAULT_SCANNED_PATHS
    excluded = set(excluded_paths) if excluded_paths is not None else set(_DEFAULT_EXCLUDED_PATHS)

    effective_paths = [path for path in paths if path not in excluded]

    scanned_files: list[str] = []
    violations: list[GuardrailViolation] = []
    for path in effective_paths:
        scanned_files.append(str(path))
        violations.extend(_scan_file_for_write_calls(path))

    return GuardrailScanResult(
        passed=not violations,
        scanned_files=scanned_files,
        violations=violations,
    )


def _scan_file_for_write_calls(path: Path) -> list[GuardrailViolation]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    violations: list[GuardrailViolation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue

        dotted_call = _dotted_call_target(node.func)
        is_write_verb = node.func.attr in _WRITE_VERB_METHOD_NAMES
        is_known_sdk_write = dotted_call in _KNOWN_SDK_WRITE_CALL_TARGETS
        if is_write_verb or is_known_sdk_write:
            violations.append(
                GuardrailViolation(file=str(path), line=node.lineno, matched_call=dotted_call)
            )
    return violations


def _dotted_call_target(func: ast.Attribute) -> str:
    """Best-effort dotted name for a call's target, e.g. "sdk_client.post"."""
    try:
        return ast.unparse(func)
    except (ValueError, TypeError):  # pragma: no cover - defensive only
        return func.attr


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_overall_risk_score(scored: list[RiskAssessment]) -> float | None:
    if not scored:
        return None
    return sum(_SEVERITY_WEIGHTS[a.severity] for a in scored) / len(scored)


def _compute_clause_type_breakdown(scored: list[RiskAssessment]) -> dict[str, dict[str, Any]]:
    """Group `scored` RiskAssessments by clause_type: count and mean asymmetry_score.

    `scored` is the same list `get_contract_report` already built (excludes
    needs_human_review severity) - never requeried here. Mirrors the
    aggregation shape `evaluation.selectors.compute_cost_report`'s
    `by_clause_type` grouping already establishes, per design.md - Decisions.
    `clause.clause_type` is guaranteed non-null and non-needs_human_review
    for every scored assessment (risk_scoring.services short-circuits to
    severity=needs_human_review whenever clause_type is None or
    needs_human_review - see risk_scoring/services.py), but the `or
    "unknown"` fallback keeps this defensive rather than reliant on that
    invariant, matching the same fallback `compute_cost_report` uses. See
    specs/reporting/clause-type-breakdown/spec.md.
    """
    scores_by_clause_type: dict[str, list[float]] = {}
    for assessment in scored:
        clause_type = assessment.clause.clause_type or "unknown"
        scores_by_clause_type.setdefault(clause_type, []).append(assessment.asymmetry_score)

    return {
        clause_type: {
            "count": len(scores),
            "mean_asymmetry_score": sum(scores) / len(scores),
        }
        for clause_type, scores in scores_by_clause_type.items()
    }


def _serialize_flagged_clause(assessment: RiskAssessment) -> dict[str, Any]:
    clause = assessment.clause
    return {
        "clause_id": clause.id,
        "sequence_index": clause.sequence_index,
        "clause_type": clause.clause_type,
        "clause_text": clause.clause_text,
        "severity": assessment.severity,
        "asymmetry_score": assessment.asymmetry_score,
        "explanation": assessment.explanation,
        "suggested_rewrite": assessment.suggested_rewrite,
        "linked_mismatch_flag_ids": list(assessment.linked_mismatch_flag_ids),
    }


def _serialize_review_clause(assessment: RiskAssessment) -> dict[str, Any]:
    clause = assessment.clause
    return {
        "clause_id": clause.id,
        "sequence_index": clause.sequence_index,
        "clause_type": clause.clause_type,
        "clause_text": clause.clause_text,
        "explanation": assessment.explanation,
    }


def _serialize_mismatch(flag: MismatchFlag) -> dict[str, Any]:
    clause = flag.extracted_term.clause
    return {
        "mismatch_id": flag.id,
        "mismatch_type": flag.mismatch_type,
        "clause_id": clause.id,
        "sequence_index": clause.sequence_index,
        "expected_value": flag.expected_value,
        "actual_value": flag.actual_value,
        "description": flag.description,
    }
