## Why

The pipeline can currently only say what a contract *claims* about payment terms (phases 1's stages 1-3); it cannot say whether those terms match what is actually happening on the payment rail. This is phase 2 of 5 in the build order — the differentiator of the whole product — and it must land after add-django-foundation (phase 1), since it reads the Contract and ExtractedTerm rows phase 1 creates and extends pipeline.services.run_pipeline with a new stage 4.

## What Changes

- Add a new `razorpay_integration` Django app, depending on `pipeline` (reads ExtractedTerm) and `contracts` (reads Contract for razorpay_reference_type/razorpay_reference_id).
- Add `PlatformRecord` model: one row per raw GET response fetched from Razorpay (payout, subscription, or token), keeping the payload verbatim for audit.
- Add `MismatchFlag` model: one row per detected mismatch, linked to the ExtractedTerm it was compared from and (when available) the PlatformRecord it was compared against.
- Implement the primary cross-check path: fetch real RazorpayX Payout history (`GET /v1/payouts` filtered by fund_account_id), derive empirical cadence (median of consecutive created_at deltas) and empirical amount (median amount) from at least 2 Payout records, and compare against ExtractedTerm.value_structured for payout_frequency terms — flagging cadence_mismatch, amount_mismatch, or missing_platform_evidence.
- Implement the secondary/stretch cross-check path: for razorpay_reference_type=subscription contracts, fetch Subscription (period, interval, item.amount, total_count) and Token (max_amount, expire_at) via GET and diff those fields exactly (no tolerance band) against contract-extracted terms.
- Generate quote-grounded MismatchFlag descriptions via core.claude_client, with mismatch existence/type always decided deterministically in code first — never by independent LLM judgment.
- Extend `pipeline.services.run_pipeline` to invoke this app's stage-4 orchestrator (`razorpay_integration.services.detect_mismatches`) after stage 3, without violating phase 1's no-in-memory-handoff decision.
- Enforce a hard guardrail: the production cross-check code path issues only GET calls against live Razorpay data; any POST calls (test-mode fixture/demo seeding) live in a separate module never imported by that path.

## Capabilities

### New Capabilities

- `razorpay-integration/payout-history-crosscheck`: Fetches a Contract's real RazorpayX Payout history and derives empirical cadence/amount to cross-check against contract-stated payout_frequency terms, since Payouts expose no queryable schedule config via API.
- `razorpay-integration/subscription-crosscheck`: Fetches a Contract's Razorpay Subscription and UPI Autopay Token configuration fields and diffs them exactly against contract-extracted terms, for razorpay_reference_type=subscription engagements.
- `razorpay-integration/mismatch-flagging`: Persists every detected mismatch as a queryable MismatchFlag with a deterministic classification and a quote-grounded, verified description, linking the ExtractedTerm and platform evidence used.

### Modified Capabilities

(none — see the sequencing note below)

## Impact

- New Django app `razorpay_integration`: models.py, services.py, selectors.py, client.py, fixtures.py, apps.py, migrations/, tests/.
- New migration adding PlatformRecord and MismatchFlag tables, with foreign keys into `contracts.Contract` and `pipeline.ExtractedTerm`.
- New dependency: the `razorpay` Python SDK (read-only usage) plus a raw-`requests` fallback, confined to `razorpay_integration/client.py`.
- `pipeline.services.run_pipeline` gains a stage-4 call into this app (see design.md for how the resulting import direction is kept non-circular).
- New settings: `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` (read-scope credentials), `CADENCE_MISMATCH_TOLERANCE_RATIO`, `AMOUNT_MISMATCH_TOLERANCE_PCT`.
- Forward-looking note: when add-django-foundation is applied and archived, no phase-1 requirement text needs a MODIFIED delta for this phase — AuditLogEntry.stage is already an unconstrained int, so stage=4 is additive by construction. If a future phase finds otherwise, revisit the pipeline audit-trail requirement then.

**Non-goals**: this phase does not implement risk scoring, severity weighting, or the aggregate report (phase 3); does not build the evaluation harness, synthetic dataset, or held-out scoring (phase 4); and does not build any user-facing viewer (phase 5). It does not perform any write/mutation against live Razorpay account data — the only writes anywhere in this app are confined to test-mode fixture/demo-seeding code in `razorpay_integration/fixtures.py`, clearly isolated from the production cross-check path.
