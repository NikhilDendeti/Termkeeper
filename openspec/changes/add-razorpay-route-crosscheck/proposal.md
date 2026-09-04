## Why

The pipeline can currently cross-check a Contract's payment terms against only two Razorpay primitives: RazorpayX Payouts (empirical cadence/amount derived from Payout history) and Subscriptions (an exact config diff against Subscription/Token fields). Both existing paths are inherently two-party — money moves from the platform (or a subscriber) to a single vendor's fund account or mandate. Neither path can represent, or cross-check, a clause that splits a single payment across more than one payee: a revenue-share, referral-commission, or marketplace-split clause. Razorpay's Route API (multi-party Transfers) is the only Razorpay primitive built around N-party splits, and its `Transfer` object (`account`, `amount`, `status`, `on_hold`, `on_hold_until`) is directly GET-able via `GET /v1/transfers/:id`, `GET /v1/payments/:id/transfers`, and `GET /v1/transfers?recipient_settlement_id=:id` — the same "read real platform evidence, never trust the contract's word alone" pattern this product has already proven twice.

No competitor in this space cross-checks a contract clause against a payment *rail's own API objects* at all, let alone a multi-party split — Route is the closest Razorpay analog to Stripe Connect, and generalizing the product's core differentiator from a 2-party pattern to an N-party one is a direct extension of what already makes this product distinctive. This is phase 2's third cross-check path, landing after add-razorpay-crosscheck (which this change depends on for `RazorpayConnector`, the `PlatformRecord`/`MismatchFlag` models, and every amount-comparison helper it reuses) and independent of add-confirmed-platform-evidence, add-risk-scoring-report, or any later phase.

**Scope decision — flat-amount splits only.** Razorpay's Route API has no native percentage-of-total field: a Transfer's `amount` is always a fixed paise integer, set at transfer-creation time. Supporting a percentage-of-revenue clause (e.g. "10% of each payment collected") would require a second GET against the parent `Payment` object and a second, structurally different comparison (derived-percentage math instead of a direct amount diff) — a distinct axis of complexity from everything this cross-check does today. That was evaluated and explicitly rejected for this change as an overscoping risk: this change covers flat-amount commission/referral clauses only (for example, "a flat $50 per referral" or "an INR 500 finder's fee per closed deal"), and a percentage-denominated term is a stated, tested non-coverage boundary — not a silent gap. See design.md's Non-Goals for the full boundary.

## What Changes

- Add `RazorpayReferenceType.TRANSFER` to `contracts.models.RazorpayReferenceType`, so a Contract can declare itself Route-referenced (its `razorpay_reference_id` holding the recipient identifier the Transfer history is fetched for), alongside the existing `payout` and `subscription` values.
- Add `PlatformRecordType.TRANSFER` to `razorpay_integration.models.PlatformRecordType`, so a fetched Transfer persists as a `PlatformRecord` exactly like a Payout or Subscription/Token record does today.
- Add `RazorpayConnector.fetch_transfers(*, recipient_settlement_id)` to `razorpay_integration/client.py`: a GET-only method, mirroring `fetch_payouts`'s shape exactly (SDK call with a raw-`requests` fallback), against `GET /v1/transfers`.
- Implement the third cross-check path: fetch a Contract's real Route Transfer history via GET, derive an empirical amount (median of fetched Transfer amounts, requiring at least 2 records — reusing the exact same median/tolerance machinery the payout path already uses) and compare it against contract-stated flat-amount payout_frequency terms, flagging amount_mismatch or missing_platform_evidence. A payout_frequency term that states a percentage (not a flat amount) or a time-based cadence is flagged trigger_condition_unverifiable instead of being compared — the Transfer object has no percentage field and no schedule field to diff against.
- Add `razorpay_integration/fixtures.py`'s `seed_transfer`, a test-mode-only POST helper for demo/dev seeding, following `seed_payout`'s pattern exactly; never imported by the production cross-check path.
- Extend `razorpay_integration.services.detect_mismatches`'s existing branch-on-`razorpay_reference_type` orchestration with a third branch for `TRANSFER`. `pipeline.services.run_pipeline` itself needs no change — it already calls `detect_mismatches` unconditionally after stage 3 and treats a stage-4 failure as non-fatal.
- Extend the frontend's Razorpay reference type selection (`UploadPage.tsx`'s select, `api/types.ts`'s union type, `utils/format.ts`'s label map) with the new `transfer` option.

## Capabilities

### New Capabilities

- `razorpay-integration/route-transfer-crosscheck`: Fetches a Contract's real Razorpay Route Transfer history and derives an empirical flat amount to cross-check against contract-stated flat-amount commission/referral terms, for `razorpay_reference_type=transfer` engagements — explicitly excluding percentage-of-revenue splits, which Route's API has no queryable field to diff against.

### Modified Capabilities

(none — `payout-history-crosscheck`, `subscription-crosscheck`, and `mismatch-flagging`, all from add-razorpay-crosscheck, are read but not modified; this change adds a third, parallel capability rather than altering either existing cross-check path.)

## Impact

- `contracts/models.py`: `RazorpayReferenceType` gains a `TRANSFER` member; new migration in `contracts` (an `AlterField` on `Contract.razorpay_reference_type`'s `choices` — no data migration, no DDL-visible change on the target database backends).
- `razorpay_integration/models.py`: `PlatformRecordType` gains a `TRANSFER` member; new migration in `razorpay_integration` (same `AlterField`-only shape, on `PlatformRecord.record_type`).
- `razorpay_integration/client.py`: new `fetch_transfers` method, following the existing GET-only guardrail the static-scan and mocked-transport tests already enforce (task 3.1/9.1 tests extend to cover it; no change to the tests' enforcement mechanism itself).
- `razorpay_integration/services.py`: new `fetch_transfer_history`, `_run_route_crosscheck`, and a small `_is_percentage_term` helper; `_create_missing_platform_evidence_flag`'s `payout_record_count` keyword argument is renamed to the path-neutral `record_count` (its one existing call site in `_run_payout_crosscheck` is updated to match — a mechanical rename, no behavior change) so the route path can reuse it as-is; `detect_mismatches` gains a third `elif` branch.
- `razorpay_integration/fixtures.py`: new `seed_transfer`, test-mode POST only.
- `razorpay_integration/selectors.py`: **no change** — `get_platform_records_for_contract(*, contract, record_type=...)` is already generic over `record_type` and works unmodified for `PlatformRecordType.TRANSFER`.
- `razorpay_integration/tests/`: new `test_route_crosscheck.py` (mirroring `test_payout_crosscheck.py`); extensions to `test_client.py`, `test_guardrails.py`, `test_fixtures_isolation.py`, `test_pipeline_integration.py`, and `factories.py`.
- `frontend/src/api/types.ts`, `frontend/src/utils/format.ts`, `frontend/src/pages/UploadPage.tsx` (+ their existing tests): add the `transfer` reference-type option.
- **No change** to `pipeline.services.run_pipeline` — it already invokes `detect_mismatches` generically after stage 3 with no path-specific logic of its own.

**Non-goals**: this change does not implement percentage-of-revenue split cross-checking (see proposal Why and design.md Non-Goals), does not fetch or model the parent Razorpay `Payment` object, does not touch Escrow or any other Razorpay product, and does not change risk scoring, reporting, or the evaluation harness. It performs no write/mutation against live Razorpay account data on the production cross-check path — the only write anywhere in this change is `fixtures.py`'s test-mode-only `seed_transfer`.
