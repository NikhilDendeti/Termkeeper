## 1. Refactor: promote cadence/amount classification helpers to selectors.py

- [x] 1.1 Promote `_is_cadence_term`, `_is_amount_term`, `_term_unit`, `_term_numeric_value`, `_TIME_UNITS`, `_DAYS_PER_UNIT` from `razorpay_integration/services.py` (private) to `razorpay_integration/selectors.py` as public names (`is_cadence_term`, `is_amount_term`, `term_unit`, `term_numeric_value`, `TIME_UNITS`, `DAYS_PER_UNIT`); leave `_PERIOD_BY_UNIT` in `services.py` unchanged (unrelated to this classification, used only by the subscription-path exact-diff comparison)
- [x] 1.2 Update every call site in `services.py` (`_run_payout_crosscheck`, `_evaluate_cadence_term`, `_evaluate_amount_term`, `_run_subscription_crosscheck`, `_evaluate_subscription_cadence_term`, `_evaluate_subscription_amount_term`) to call `razorpay_selectors.<name>` via the already-existing `from razorpay_integration import selectors as razorpay_selectors` import - no new import needed, no behavior change
- [x] 1.3 Repo-wide search confirming no test references the six private names directly (`grep -rn` for each, `*.py`); none found, so no test file needed a rename - only new direct-unit-test coverage for the promoted public names
- [x] 1.4 Add `TestCadenceAmountClassification` to `razorpay_integration/tests/test_selectors.py` covering `term_unit` (lowercase/strip, missing/blank), `term_numeric_value` (coercion, missing), `is_cadence_term`/`is_amount_term` (recognized unit, non-time unit, no numeric_value), and `TIME_UNITS`/`DAYS_PER_UNIT` key-set agreement
- [x] 1.5 Run the full existing `razorpay_integration` test suite and confirm zero regressions (behavior-preserving rename only)

## 2. `OverdueStatus` and `list_overdue_statuses` (overdue-payment-detection spec)

- [x] 2.1 Add `razorpay_integration.selectors.OverdueStatus` (frozen dataclass: `term_id`, `is_overdue`, `days_since_last_payout`, `expected_interval_days`, `latest_payout_date`)
- [x] 2.2 Implement `list_overdue_statuses(*, contract) -> list[OverdueStatus]` per design.md - Decision 3: scope-gate on `razorpay_reference_type == PAYOUT`, short-circuit to `[]` on zero Payout PlatformRecords, iterate the contract's clauses/ExtractedTerm rows filtering to cadence-type `payout_frequency` terms, compute `is_overdue` via `days_since_last_payout > expected_interval_days * (1 + settings.CADENCE_MISMATCH_TOLERANCE_RATIO)`
- [x] 2.3 New `razorpay_integration/tests/test_overdue_detection.py`: not-overdue (well within interval), overdue (past interval + tolerance), exactly-at-boundary (not overdue) and one-day-past (overdue), zero PlatformRecords (empty, not a false verdict), amount-type term excluded, Subscription-referenced contract excluded, non-`payout_frequency` term type ignored, multiple qualifying terms on different clauses each independently evaluated, multiple qualifying terms on the *same* clause each independently evaluated, `latest_payout_date` uses the max `razorpay_created_at` across records (not an arbitrary one) - per every scenario in specs/razorpay-integration/overdue-payment-detection/spec.md
- [x] 2.4 Add a test asserting `razorpay_integration/services.py`'s source text never references `list_overdue_statuses` or `OverdueStatus`, mirroring `test_fixtures_isolation.py`'s phrase-absence enforcement style, per "Overdue detection never runs during stage-4 mismatch detection"
- [x] 2.5 Confirm every new test uses `timezone.now()`-relative fixture timestamps (never a fixed wall-clock date) and runs with zero `ENABLE_STAGE_4`/real-key dependency

## 3. Wire into `reporting` (reasoning-chain API)

- [x] 3.1 Add `overdue_statuses: list[razorpay_selectors.OverdueStatus]` (default `[]`) to `reporting.selectors.ClauseReasoningChain`
- [x] 3.2 Update `get_contract_reasoning_chain` to call `razorpay_selectors.list_overdue_statuses(contract=contract)` once per contract (before the per-clause loop), index the result by `term_id`, and populate each clause's `overdue_statuses` from the entries whose `term_id` belongs to that clause's own `extracted_terms`
- [x] 3.3 Add `reporting.serializers.OverdueStatusSerializer` (mirrors `OverdueStatus` field-for-field) and an `overdue_statuses = OverdueStatusSerializer(many=True)` field on `ClauseReasoningChainSerializer`
- [x] 3.4 Add `TestOverdueStatusesOnReasoningChain` to `reporting/tests/test_selectors.py`: overdue term surfaces on its clause, clause with no qualifying term has an empty list, an overdue status is attributed only to its owning clause (never leaks to a sibling clause), amount-type term never surfaces a status, Subscription-referenced contract never surfaces a status
- [x] 3.5 Add `TestClauseReasoningChainSerializerOverdueStatuses` to `reporting/tests/test_serializers.py`: statuses serialize correctly when present, defaults to an empty list when absent
- [x] 3.6 Run the full existing `reporting` test suite and confirm zero regressions

## 4. Frontend

- [x] 4.1 Add `OverdueStatusEntry` interface to `frontend/src/api/types.ts`, mirroring `OverdueStatusSerializer` field-for-field; add `overdue_statuses: OverdueStatusEntry[]` to the `ClauseReasoningChain` interface
- [x] 4.2 Add `.overdue-banner` to `frontend/src/index.css`, reusing `.confirmed-banner`'s pill shape with `--color-warning*` tokens (the same tokens `.needs-review-banner` already uses) rather than inventing a new visual pattern
- [x] 4.3 Render the overdue banner in `ContractDetailPage.tsx`'s `ReasoningChainSection`, per extracted term, when that term's `term_id` has a matching `overdue_statuses` entry with `is_overdue=true`: "Overdue — expected every {expected_interval_days} days, last payout was {days_since_last_payout} days ago", using the existing `clock` icon
- [x] 4.4 Update `ContractDetailPage.test.tsx`'s `ClauseReasoningChain` fixtures with the now-required `overdue_statuses` field; add tests confirming the banner renders when a term is overdue and does not render when not overdue or when `overdue_statuses` is empty
- [x] 4.5 Run `npm run test -- --run` and `npm run build` in `frontend/` and confirm all green with zero TypeScript errors

## 5. OpenSpec

- [x] 5.1 Write proposal.md, design.md, tasks.md (this file), and the ADDED-requirements spec delta at `specs/razorpay-integration/overdue-payment-detection/spec.md`
- [x] 5.2 Run `openspec validate add-overdue-payment-detection --strict` and fix anything it flags

## 6. Full verification

- [x] 6.1 Run the full backend test suite (`pytest -q`) and confirm no regressions anywhere in the project, alongside every new test added above
- [x] 6.2 Run `mypy` across `razorpay_integration`, `reporting`, and `contracts` and confirm zero errors
- [x] 6.3 Run `npm run test -- --run` and `npm run build` in `frontend/` and confirm all green
- [x] 6.4 Manually verify the live rendering: seed a temporary Contract/Clause/ExtractedTerm/PlatformRecord combination in the local dev database, confirm the overdue banner renders correctly in the running app, then remove the temporary rows
