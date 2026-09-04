## Purpose

Live, request-time detection of whether a Payout-referenced Contract's next payout is already overdue, computed from already-persisted `ExtractedTerm` and `PlatformRecord` rows on every read - the same recompute-don't-trust pattern the audit-log-integrity and guardrail-verification capabilities already establish - since "overdue" is a function of the current calendar date, not of any new analysis, and would go silently stale if it were ever written once as a persisted `MismatchFlag`.

## ADDED Requirements

### Requirement: Overdue status is computed live, never persisted
The system SHALL compute a Contract's overdue-payment status by recomputing it from currently-persisted `ExtractedTerm` and `PlatformRecord` rows on every invocation, and SHALL NOT persist an overdue verdict as a `MismatchFlag` or as any other database row.

#### Scenario: Repeated calls reflect current data, not a cached verdict
- **WHEN** `razorpay_integration.selectors.list_overdue_statuses` is called twice for the same Contract, with a new Payout `PlatformRecord` persisted for that Contract between the two calls
- **THEN** the second call's result reflects the newly persisted `PlatformRecord`, and no prior call's result is read from, or written to, any stored table

#### Scenario: Passing time alone changes the result with no new pipeline activity
- **WHEN** `list_overdue_statuses` is called for a Contract whose most recent Payout record is old enough that the elapsed time since it now exceeds the contract-stated interval plus tolerance, with no new `ExtractedTerm` or `PlatformRecord` written since the last pipeline run
- **THEN** the result reports that term's `is_overdue` as `True`, demonstrating the verdict changes with the calendar alone and is never fixed at pipeline-run time

### Requirement: Overdue detection never runs during stage-4 mismatch detection
The system SHALL NOT compute or reference overdue-payment status from within `razorpay_integration.services.detect_mismatches` or any function it calls, and SHALL NOT create a `MismatchFlag` of an overdue-payment type.

#### Scenario: detect_mismatches's call graph never reaches overdue computation
- **WHEN** `razorpay_integration.services.detect_mismatches` runs for any Contract
- **THEN** no call to `razorpay_integration.selectors.list_overdue_statuses` occurs as part of that run, and no `MismatchFlag` row representing an overdue payment is created

### Requirement: Scope is Payout-referenced contracts and cadence-type payout_frequency terms only
The system SHALL compute overdue status only for Contracts whose `razorpay_reference_type` is `payout`, and only for `payout_frequency` `ExtractedTerm` rows that are cadence-type (a recognized time unit: day(s), week(s), month(s), or year(s)). Subscription-referenced Contracts and amount-type `payout_frequency` terms are explicit non-goals of this capability, not silently skipped edge cases.

#### Scenario: Subscription-referenced contract yields no overdue statuses
- **WHEN** `list_overdue_statuses` is called for a Contract whose `razorpay_reference_type` is `subscription`
- **THEN** the result is an empty list, and no PlatformRecord or ExtractedTerm query is issued for that Contract

#### Scenario: Amount-type payout_frequency term is excluded
- **WHEN** a Payout-referenced Contract has a `payout_frequency` ExtractedTerm whose `value_structured.unit` is not a recognized time unit (an amount-type term, per the same classification the persisted cadence/amount cross-check already uses)
- **THEN** that term produces no `OverdueStatus` entry, regardless of how much Payout history exists for the Contract

#### Scenario: Cadence-type term on a Payout-referenced contract is evaluated
- **WHEN** a Payout-referenced Contract has a `payout_frequency` ExtractedTerm whose `value_structured.unit` is a recognized time unit
- **THEN** that term is evaluated for overdue status against the Contract's observed Payout history

### Requirement: Zero platform evidence yields not-applicable, never a false overdue verdict
The system SHALL return no `OverdueStatus` for a Contract's cadence-type `payout_frequency` terms when that Contract has zero Payout `PlatformRecord` rows, rather than reporting `is_overdue=True` or `is_overdue=False` from no evidence.

#### Scenario: Contract with no Payout records yields an empty result
- **WHEN** `list_overdue_statuses` is called for a Payout-referenced Contract with zero Payout `PlatformRecord` rows and at least one cadence-type `payout_frequency` ExtractedTerm
- **THEN** the result is an empty list for that Contract, distinct from and never conflicting with the `missing_platform_evidence` MismatchFlag stage 4 may already have created for the same term

### Requirement: Overdue determination formula
The system SHALL determine a cadence-type `payout_frequency` term's overdue status as: `latest_payout_date` = the maximum `razorpay_created_at` across the Contract's Payout `PlatformRecord` rows; `expected_interval_days` = the term's `numeric_value` multiplied by its unit's day-equivalent; `days_since_last_payout` = the whole number of days between `latest_payout_date` and the current time; `is_overdue` = `True` exactly when `days_since_last_payout` strictly exceeds `expected_interval_days` multiplied by `(1 + settings.CADENCE_MISMATCH_TOLERANCE_RATIO)`. The system SHALL reuse `settings.CADENCE_MISMATCH_TOLERANCE_RATIO` for this comparison and SHALL NOT introduce a separate overdue-specific tolerance setting.

#### Scenario: Well within the expected interval is not overdue
- **WHEN** a Contract's most recent Payout occurred well within its stated cadence interval (e.g. a 30-day cadence term with the last Payout 5 days ago)
- **THEN** that term's `OverdueStatus.is_overdue` is `False`

#### Scenario: Past the interval and tolerance is overdue
- **WHEN** a Contract's most recent Payout occurred longer ago than its stated cadence interval inflated by `CADENCE_MISMATCH_TOLERANCE_RATIO` (e.g. a 30-day cadence term, a 0.2 tolerance ratio, and the last Payout more than 36 days ago)
- **THEN** that term's `OverdueStatus.is_overdue` is `True`

#### Scenario: Exactly at the tolerance boundary is not overdue
- **WHEN** `days_since_last_payout` equals `expected_interval_days * (1 + CADENCE_MISMATCH_TOLERANCE_RATIO)` exactly
- **THEN** that term's `OverdueStatus.is_overdue` is `False`, matching the strict-inequality boundary the persisted cadence_mismatch comparison already uses

### Requirement: Each qualifying term is evaluated independently
The system SHALL return one `OverdueStatus` per qualifying `payout_frequency` ExtractedTerm on a Contract, evaluated independently against that same Contract's observed Payout history, when a Contract has more than one such term across one or more clauses.

#### Scenario: Multiple qualifying terms each produce their own status
- **WHEN** a Contract has two cadence-type `payout_frequency` ExtractedTerm rows (whether on the same Clause or on two different Clauses) with different stated intervals
- **THEN** `list_overdue_statuses` returns one `OverdueStatus` per term, each keyed to its own `term_id`, with `is_overdue` determined independently per term's own `expected_interval_days`

### Requirement: Overdue status is surfaced on the reasoning-chain API at clause grain
The system SHALL expose each qualifying term's live overdue status on `ClauseReasoningChain`/`ClauseReasoningChainSerializer`'s `overdue_statuses` field, scoped to the clause that owns the originating `ExtractedTerm`, always present as a list (possibly empty), never omitted or null.

#### Scenario: A clause with an overdue term surfaces it in the reasoning chain
- **WHEN** the reasoning-chain endpoint is read for a Contract whose payment-schedule Clause carries a cadence-type `payout_frequency` term that `list_overdue_statuses` reports as overdue
- **THEN** that Clause's `overdue_statuses` entry in the response includes an entry with `is_overdue=True` for that term's `term_id`

#### Scenario: A clause with no qualifying term has an empty overdue_statuses list
- **WHEN** the reasoning-chain endpoint is read for a Clause with no cadence-type `payout_frequency` ExtractedTerm (no extracted terms at all, or only non-qualifying ones)
- **THEN** that Clause's `overdue_statuses` is an empty list, not omitted and not null
