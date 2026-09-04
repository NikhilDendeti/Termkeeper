## Context

See proposal.md for motivation. Confirmed by reading the current code before writing this design (some of it was touched by other work earlier this session):

- `razorpay_integration/services.py::_run_payout_crosscheck` already computes an *empirical* cadence from a Contract's Payout `PlatformRecord` history (`_compute_empirical_cadence_days`, a median of consecutive `razorpay_created_at` deltas, requiring at least 2 records) and compares it against a `payout_frequency` ExtractedTerm's stated cadence via `_evaluate_cadence_term`, using `settings.CADENCE_MISMATCH_TOLERANCE_RATIO` as the deviation tolerance. This produces a persisted `cadence_mismatch` MismatchFlag, written once, at stage-4 run time.
- `_is_cadence_term`/`_is_amount_term`/`_term_unit`/`_term_numeric_value`/`_TIME_UNITS`/`_DAYS_PER_UNIT` (private, in `services.py`) classify a `payout_frequency` ExtractedTerm's `value_structured` (`{numeric_value, unit}`) as either a time-based cadence (unit in `{day(s), week(s), month(s), year(s)}`) or a flat amount. `_PERIOD_BY_UNIT` is a separate, smaller mapping used only by the subscription path's exact-field diff (`_evaluate_subscription_cadence_term`) - it is not part of this refactor.
- `razorpay_integration/selectors.py` (pre-existing) already holds `get_platform_records_for_contract`, `list_mismatch_flags_for_contract`, and `get_latest_payout_records` - every non-trivial read for this app already lives here, per the project-wide services.py-writes / selectors.py-reads convention documented in this app's `services.py` module docstring.
- `reporting/selectors.py::get_contract_reasoning_chain` builds one `ClauseReasoningChain` per Clause, joining `pipeline`'s ExtractedTerm rows, `risk_scoring`'s linked MismatchFlags, `razorpay_integration`'s confirmed PlatformRecords (`_get_verified_platform_records`), and `risk_scoring`'s RiskAssessment - every clause included regardless of state, per specs/api/reasoning-chain/spec.md.
- `Contract.razorpay_reference_type` is `payout` or `subscription` (`contracts.models.RazorpayReferenceType`); an ExtractedTerm belongs to exactly one Clause (`pipeline.models.ExtractedTerm.clause`, FK), and a Clause belongs to exactly one Contract - so a payment-schedule Clause is not a fixed 1:1 with a Contract (a Contract can have more than one clause carrying a `payout_frequency` term, and in principle more than one such term within one clause), which is why the core function returns a list rather than a single optional result.

## Goals / Non-Goals

**Goals**
- Answer "is this Contract's next payout already late, as of right now" from data that already exists, recomputed on every read, never cached or stored.
- Zero new Razorpay API calls, zero new database writes, zero new Django settings.
- Reuse the exact cadence/amount classification and tolerance machinery the persisted cadence_mismatch check already validated, rather than reimplementing a parallel version of the same logic.
- Surface the result through the same reasoning-chain surface (`reporting.selectors`/`reporting.serializers`/`frontend/src/api/types.ts`) every other per-clause verdict already goes through, at whichever grain (clause vs. contract) the actual ExtractedTerm-to-Clause relationship supports honestly.

**Non-Goals**
- Persisting an overdue verdict as a `MismatchFlag` or any other row. See proposal.md - Why (calendar drift makes a persisted verdict silently stale).
- Running any part of this during `detect_mismatches` (stage 4). Stage 4 is for evidence gathering and deterministic-comparison-at-a-point-in-time; this is a pure read over data stage 4 already gathered, evaluated at a different point in time (now) than stage 4 ran.
- Overdue detection for amount-type `payout_frequency` terms. A flat amount ("$500 per payout") states no interval - there is nothing for "days since last payout" to be measured against. This is a stated, tested scope boundary (see spec.md's dedicated scenario), not a silent gap.
- Overdue detection for Subscription-referenced Contracts. A Subscription's cadence is diffed by exact config field (`period`/`interval` against Razorpay's own Subscription object) via `_evaluate_subscription_cadence_term` - a fundamentally different comparison (config-diff, not empirical-history-derived) that has no analogous "time since last observed event" concept to generalize this capability to. Also a stated, tested scope boundary.
- A new tolerance setting. See proposal.md - Why.
- Any change to `pipeline.services.run_pipeline`, `ENABLE_STAGE_4` gating, or any existing persisted MismatchFlag type or comparison path.

## Decisions

### Decision 1: Live selector-layer computation, not a stage-4 write

**Chosen:** `razorpay_integration.selectors.list_overdue_statuses(*, contract) -> list[OverdueStatus]` - a plain function, no model, called directly by `reporting.selectors.get_contract_reasoning_chain` on every request for that endpoint (and by any other future caller, the same way `verify_audit_chain`/`scan_razorpay_guardrail` are called on every request for their respective endpoints).

An alternative considered and rejected: compute overdue status once during `detect_mismatches` (stage 4) and persist it as a new MismatchFlag type (e.g. `payment_overdue`). Rejected because a MismatchFlag written today asserts a fact ("as of the time this pipeline ran, X was true") that silently stops being the actual current truth the instant real calendar time moves past the point where the *next* payout was due - and nothing re-runs stage 4 just because a date passed. A viewer reading a report three weeks after the last pipeline run would see a stale "not overdue" (or worse, a stale "overdue" that has since been resolved by a payout PlatformRecord fetched by some later, unrelated pipeline re-run) with no indication that the verdict's freshness has anything to do with when it was computed rather than the actual current date. Every other "is this still true right now" claim in this codebase (`scan_razorpay_guardrail`'s "is the source code still guardrail-clean", `verify_audit_chain`'s "is the hash chain still unbroken") is answered the same way - a pure function, recomputed on every call, wrapped by whatever surface needs it - and this is the same shape of claim.

### Decision 2: Promote classification helpers to `selectors.py`, public

**Chosen:** `is_cadence_term`, `is_amount_term`, `term_unit`, `term_numeric_value`, `TIME_UNITS`, `DAYS_PER_UNIT` move from `services.py` (private) to `selectors.py` (public). `services.py` imports them via the module-qualified `razorpay_selectors.<name>` it already uses for every other selectors.py call (`razorpay_selectors.get_platform_records_for_contract`, etc.) - no new import statement needed, only updated call sites.

This is a straightforward application of the project's own stated convention ("Every non-trivial read goes through a function here" - both `selectors.py` module docstrings, `services.py`'s own module docstring naming the services.py-writes/selectors.py-reads split explicitly) to a case that convention had not yet reached: classifying an ExtractedTerm's `value_structured` shape is a pure read/computation over already-persisted data, indistinguishable in kind from `get_platform_records_for_contract` or `list_mismatch_flags_for_contract` - it was only ever in `services.py` because the persisted cadence/amount cross-check was the first (and, until now, only) consumer. `list_overdue_statuses` needs exactly the same classification and has no reason to duplicate it. This mirrors add-audit-log-hash-chain's own refactor precedent almost exactly: that change collapsed three independent, drifting `_create_audit_log_entry` write helpers into one shared function *because* a second consumer (stage 4, stage 5) needed the same write logic stage 1-3 already had; here, a second consumer (`list_overdue_statuses`) needs the same read logic the persisted cadence check already has, and the fix is the same shape - promote to the one module already designated to hold shared reads, not fork a second copy.

`_PERIOD_BY_UNIT` is deliberately left where it is (private, in `services.py`) - it is a different mapping (unit -> Razorpay Subscription `period` string, not unit -> days) used only by the subscription-path exact-diff comparison, which this change does not touch and which has no live-overdue analog (see Non-Goals).

A repo-wide search (`grep -rn` for each of the six private names, restricted to `*.py`) before writing this design confirmed no test file references any of them by their private name directly - every existing test exercises them indirectly through `_run_payout_crosscheck`/`_run_subscription_crosscheck`'s public entry points, so the rename requires no test *rewrite*, only new direct-unit-test coverage for the now-public names (task list, `razorpay_integration/tests/test_selectors.py`).

### Decision 3: `OverdueStatus` and `list_overdue_statuses` shape

```python
@dataclass(frozen=True)
class OverdueStatus:
    term_id: uuid.UUID
    is_overdue: bool
    days_since_last_payout: int
    expected_interval_days: float
    latest_payout_date: datetime


def list_overdue_statuses(*, contract: Contract) -> list[OverdueStatus]:
    if contract.razorpay_reference_type != RazorpayReferenceType.PAYOUT:
        return []

    payout_records = list(get_platform_records_for_contract(
        contract=contract, record_type=PlatformRecordType.PAYOUT
    ))
    if not payout_records:
        return []

    latest_payout_date = max(r.razorpay_created_at for r in payout_records)
    days_since_last_payout = (django_timezone.now() - latest_payout_date).days

    statuses = []
    for clause in contracts_selectors.list_clauses_for_contract(contract=contract):
        for term in pipeline_selectors.list_extracted_terms_for_clause(clause=clause):
            if term.term_type != TermType.PAYOUT_FREQUENCY.value or not is_cadence_term(term):
                continue
            numeric_value = term_numeric_value(term)
            unit = term_unit(term)
            expected_interval_days = numeric_value * DAYS_PER_UNIT[unit]
            is_overdue = days_since_last_payout > expected_interval_days * (
                1 + settings.CADENCE_MISMATCH_TOLERANCE_RATIO
            )
            statuses.append(OverdueStatus(
                term_id=term.id, is_overdue=is_overdue,
                days_since_last_payout=days_since_last_payout,
                expected_interval_days=expected_interval_days,
                latest_payout_date=latest_payout_date,
            ))
    return statuses
```

Points worth calling out explicitly:

- **Scope gate first, cheaply.** `razorpay_reference_type != PAYOUT` short-circuits before any query - a Subscription-referenced Contract never issues even the PlatformRecord lookup, mirroring `fetch_payout_history`'s own no-op-for-wrong-reference-type shape in `services.py`.
- **`latest_payout_date` and `days_since_last_payout` are computed once per contract, not once per term.** Every qualifying term on the same Contract is measured against the same observed Payout history and the same "now" - recomputing `timezone.now()` per term would risk two terms in the same call disagreeing by microseconds for no reason, and would just be wasted work.
- **Zero-records threshold is 1, not 2.** The persisted `cadence_mismatch`/`missing_platform_evidence` split in `_run_payout_crosscheck` requires *2* Payout records (a median needs at least 2 points to be meaningful). This live check only ever needs the single most recent Payout - "how long since the last one" is well-defined with exactly 1 data point. Requiring 2 here would incorrectly report "not applicable" for a Contract with exactly 1 real Payout on record, which is precisely the situation where a viewer most wants to know if that single payout's follow-up is already late.
- **Iteration mirrors `services._list_payout_frequency_terms` exactly** (`contracts_selectors.list_clauses_for_contract` → `pipeline_selectors.list_extracted_terms_for_clause` per clause), because it needs the same set of candidate terms - but this function filters to `is_cadence_term` only (never `is_amount_term`), since an amount term has no interval to be overdue against (Non-Goals).
- **Strict inequality at the tolerance boundary.** `is_overdue = days_since_last_payout > expected_interval_days * (1 + tolerance)` - a gap exactly equal to the tolerance-inflated interval is *not* overdue, matching `_deviation_ratio`'s own `<=` (not overdue) / `>` (mismatch) boundary convention in `_evaluate_cadence_term`.
- **`ExtractedTerm.id` uniquely keys each `OverdueStatus`** (`term_id`), not `clause_id` - this is what lets `reporting.selectors.get_contract_reasoning_chain` distribute results back to the correct clause even when a Contract has more than one qualifying term across more than one clause (see Decision 4), and what lets a caller tell two qualifying terms on the *same* clause apart.

### Decision 4: `overdue_statuses` lives on `ClauseReasoningChain` (clause-level), not on the contract-level aggregate report

Two placements were evaluated, per the task's own framing:

**Considered: a contract-level field on `get_contract_report`'s aggregate dict.** Rejected. `get_contract_report` aggregates *scored* clauses (RiskAssessment rows) and *flagged* mismatches (MismatchFlag rows) - both are things that were decided by a prior pipeline stage and persisted. `overdue_statuses` is neither: it has no RiskAssessment, no MismatchFlag, no stage-of-origin. Bolting a live, unpersisted computation onto the one endpoint whose entire contract (`get_contract_report`'s own docstring: "Issues no call to the Claude API - every input is already persisted") is built around aggregating already-persisted rows would blur that boundary for every future reader of `get_contract_report`. It would also lose the natural key: `get_contract_report` has no clause-scoped substructure an overdue term could attach to without inventing one.

**Chosen: `overdue_statuses: list[OverdueStatus]` on `ClauseReasoningChain`.** `get_contract_reasoning_chain` already includes every clause "regardless of clause_type or review state" (spec: api/reasoning-chain) and already carries two other pieces of live-vs-persisted evidence at exactly this same per-clause grain: `mismatch_flags` (persisted, but joined live via `risk_scoring_selectors.get_linked_mismatch_flags`) and `verified_platform_records` (computed live, per read, by `_get_verified_platform_records` - itself already a "no new MismatchFlag row, just a computed-on-read view over existing PlatformRecord data" precedent this exact capability extends). An `ExtractedTerm` belongs to exactly one `Clause` (FK), so "which clause does this overdue term belong to" has one honest, non-invented answer - unlike the contract-level placement, nothing here needs to pick a "primary" clause when a Contract has more than one payment-schedule clause.

**List, not single optional, matching `mismatch_flags`'s own shape.** The task description raised two framings - "populated only for the clause whose ExtractedTerm produced an OverdueStatus, None otherwise" (implying a single optional value) vs. "the real function returns `list[OverdueStatus]`... so multiple payment-schedule clauses in one contract are each checked independently" (implying a list). These are reconciled by making `ClauseReasoningChain.overdue_statuses` a list (not `OverdueStatus | None`): a single clause can itself carry more than one `payout_frequency` ExtractedTerm (nothing in the data model prevents it), and collapsing that to one optional value would silently drop a second qualifying term on the same clause. A list, defaulting to empty, is exactly `mismatch_flags`'s and `verified_platform_records`' own established shape on this same dataclass - "always present, possibly empty" - so this field introduces no new convention for a reader of `ClauseReasoningChain` to learn.

**Computed once per contract, distributed by `term_id`.** `get_contract_reasoning_chain` calls `razorpay_selectors.list_overdue_statuses(contract=contract)` exactly once, before the per-clause loop (`list_overdue_statuses` already walks every clause internally to find its candidate terms - calling it once per clause inside the loop would make it quadratic for no benefit). The single result list is then indexed by `term_id` and each clause's `overdue_statuses` is filtered to the `OverdueStatus` entries whose `term_id` is among that clause's own `extracted_terms` - an O(1) dict lookup per term, not a second selector call per clause.

## Risks / Trade-offs

- **[Risk] `django_timezone.now()` makes `list_overdue_statuses`'s output non-deterministic across two calls a few milliseconds apart** (in the boundary case where `days_since_last_payout`'s truncated `.days` value ticks over between calls). → **Mitigation**: accepted, and inherent to any live "how long ago" computation - the same non-determinism-at-the-instant already exists for `verify_audit_chain`/`scan_razorpay_guardrail`'s "as of right now" framing. Tests avoid the flakiness by constructing fixture timestamps relative to `timezone.now()` at test-run time (e.g. `timezone.now() - timedelta(days=N)`), never against a fixed wall-clock date - see tasks.md.
- **[Risk] Computing `list_overdue_statuses` inside `get_contract_reasoning_chain` adds one extra PlatformRecord query and one extra pair of per-clause queries (clauses, extracted terms) to that endpoint**, beyond what it already issues for `mismatch_flags`/`verified_platform_records`/`risk_assessment`. → **Mitigation**: accepted as a query-count trade-off consistent with the rest of this function's existing N+1-per-clause shape (documented, not hidden - `_get_verified_platform_records` already adds its own extra PlatformRecord queries per clause today); calling `list_overdue_statuses` once per contract rather than once per clause keeps this a fixed, small overhead rather than compounding it further.
- **[Risk] A future stage-4 change could accidentally start calling `list_overdue_statuses` (or duplicate its logic) from inside `detect_mismatches`**, reintroducing the exact staleness problem this design avoids. → **Mitigation**: `list_overdue_statuses` lives in `selectors.py`, and `services.py`'s existing module docstring already states the write-path/read-path boundary in prose; the task list includes a test asserting `detect_mismatches`'s transitive call graph contains no reference to `list_overdue_statuses`/`OverdueStatus`, mirroring the existing `test_fixtures_isolation.py` "X is absent from `detect_mismatches`'s transitive import graph" pattern this codebase already uses to enforce this class of boundary.

## Migration Plan

- No database migration - `OverdueStatus` is a plain dataclass, not a model; nothing new is persisted.
- No new Django setting - `CADENCE_MISMATCH_TOLERANCE_RATIO` is reused unchanged.
- Rollout order: (1) the `services.py` → `selectors.py` promotion refactor, verified against the full existing `razorpay_integration` test suite with zero behavior change; (2) `OverdueStatus` + `list_overdue_statuses`, with its own direct unit tests, in isolation; (3) `reporting.selectors`/`reporting.serializers` wiring, verified against the existing reasoning-chain test suite plus new coverage; (4) frontend type + banner, verified with `npm run build`/`npm run test`.
- Rollback: revert (3) and (4) to drop the field from the public API surface (additive-only, so reverting is a plain field removal); revert (2) to remove `list_overdue_statuses`; the (1) refactor can be left in place independently (it is a pure, behavior-preserving rename with its own passing test suite) or reverted together - neither direction touches any persisted row or requires a data migration.
