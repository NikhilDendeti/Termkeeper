## 1. App scaffolding

- [x] 1.1 Create the `razorpay_integration` Django app (apps.py, migrations/, tests/) and add it to INSTALLED_APPS; verify with `python manage.py check`
- [x] 1.2 Add `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `CADENCE_MISMATCH_TOLERANCE_RATIO`, `AMOUNT_MISMATCH_TOLERANCE_PCT`, `ENABLE_STAGE_4` settings, env-var-backed with defaults; verify `python manage.py check` still passes with settings loaded

## 2. Models

- [x] 2.1 Define `PlatformRecord` (id UUID pk, contract FK, record_type enum[payout,subscription,token], razorpay_id str, payload JSONField, razorpay_created_at, fetched_at) — fields/constraints only, no business logic; verify with `python manage.py makemigrations --check`
- [x] 2.2 Define `MismatchFlag` (id UUID pk, extracted_term FK(ExtractedTerm), platform_record FK(PlatformRecord, null=True), mismatch_type enum[cadence_mismatch,amount_mismatch,missing_platform_evidence,trigger_condition_unverifiable], expected_value JSONField, actual_value JSONField, description TextField, created_at); verify with a factory_boy test that creates one instance of each mismatch_type
- [x] 2.3 Generate and hand-review the migration for both models; verify `python manage.py migrate` applies cleanly against a fresh test database

## 3. Read-only Razorpay client

- [x] 3.1 Implement `razorpay_integration/client.py`'s `RazorpayConnector` with `fetch_payouts(fund_account_id)`, `fetch_subscription(subscription_id)`, `fetch_token(token_id)` — GET-only, razorpay SDK primary with raw-requests fallback; verify with a static-scan test asserting no POST/PUT/PATCH/DELETE call appears anywhere reachable from these methods
- [x] 3.2 Implement `razorpay_integration/fixtures.py` as a fully separate test-mode seeding module (Contact/Fund Account/Payout/Subscription/Token creation); verify with a test asserting `fixtures` does not appear in the transitive import graph of `detect_mismatches`

## 4. Payout-history cross-check (payout-history-crosscheck spec)

- [x] 4.1 Implement `services.fetch_payout_history(*, contract)` persisting one `PlatformRecord(record_type=payout)` per fetched Payout; verify with a mocked-API test asserting >=2 payouts produce matching PlatformRecord rows with correct payload, per "Subscription and token fields fetched for diffing" style evidence persistence
- [x] 4.2 Implement empirical cadence (median of consecutive created_at deltas) and empirical amount (median amount) computation requiring >=2 Payout records; verify with unit tests covering 2 payouts, 3 payouts, and an outlier-skewed set, per "Empirical cadence derivation from payout history" and "Empirical amount derivation from payout history"
- [x] 4.3 Implement cadence_mismatch detection against `CADENCE_MISMATCH_TOLERANCE_RATIO`; verify with a within-tolerance test (no flag) and an over-tolerance test (flag created), per "Cadence mismatch detection against a configured tolerance"
- [x] 4.4 Implement amount_mismatch detection against `AMOUNT_MISMATCH_TOLERANCE_PCT`; verify with a within-tolerance test (no flag) and an over-tolerance test (flag created), per "Amount mismatch detection against a configured tolerance"
- [x] 4.5 Implement missing_platform_evidence flagging when fewer than 2 Payout records exist; verify with tests for 0 and 1 payout each producing a missing_platform_evidence MismatchFlag with platform_record null, per "Missing platform evidence when insufficient payout history exists"
- [x] 4.6 Verify no generated description or persisted string in the payout path contains the phrase "schedule config" (or equivalent), per "No claim of a payout schedule configuration" — a grep-based test over generated description output

## 5. Subscription cross-check (subscription-crosscheck spec)

- [x] 5.1 Implement `services.fetch_subscription_config(*, contract)` fetching Subscription (period, interval, item.amount, total_count) and Token (max_amount, expire_at) via GET, persisting `PlatformRecord(record_type=subscription)` and `PlatformRecord(record_type=token)`; verify with a mocked-API test asserting both records persist with correct payload, per "Subscription and token fields fetched for diffing"
- [x] 5.2 Implement exact field diff (no tolerance) between fetched fields and corresponding ExtractedTerm values; verify with a test confirming any nonzero item.amount difference produces an amount_mismatch, per "Exact field diff with no tolerance band"
- [x] 5.3 Implement trigger_condition_unverifiable flagging for ExtractedTerms with no mappable Subscription/Token field; verify with a test using a milestone_trigger term producing a trigger_condition_unverifiable flag with platform_record null, per "Trigger condition unverifiable for non-diffable terms"
- [x] 5.4 Restrict the subscription cross-check to `razorpay_reference_type=subscription` Contracts; verify with a test confirming zero Subscription/Token GET calls and zero subscription-path flags for a payout-referenced Contract, per "Secondary path restricted to subscription-referenced contracts"

## 6. Mismatch persistence and quote-grounded descriptions (mismatch-flagging spec)

- [x] 6.1 Implement deterministic mismatch_type and creation decisions entirely in code, before any LLM call; verify with a test asserting zero `core.claude_client` calls occur for a comparison that produces no mismatch, per "Deterministic mismatch classification precedes any LLM involvement"
- [x] 6.2 Implement `MismatchFlag` persistence linking `extracted_term` and `platform_record` (nullable only for missing_platform_evidence/trigger_condition_unverifiable); verify with a test per mismatch_type checking platform_record nullability, per "Persisted MismatchFlag links term and platform evidence"
- [x] 6.3 Implement quote-grounded description generation via `core.claude_client.get_structured_completion` and `quote_is_verbatim` for expected_value and actual_value; verify with a test asserting `quote_is_verbatim` returns True for both quotes, and a second test forcing a failed verification to confirm the deterministic-template fallback, per "Quote-grounded description generation"
- [x] 6.4 Persist an `AuditLogEntry(stage=4, ...)` for each `detect_mismatches` LLM-based description call, reusing phase 1's `AuditLogEntry` model verbatim; verify with a test confirming stage=4 rows appear via `pipeline.selectors.get_audit_trail(contract=contract)`
- [x] 6.5 Verify a MismatchFlag's full evidence chain (extracted_term -> platform_record or explicit null -> description) is retrievable from persisted storage without re-running the pipeline, per "Every MismatchFlag is queryable with its full evidence chain"

## 7. Pipeline integration

- [x] 7.1 Implement `services.detect_mismatches(*, contract)` as the stage-4 orchestrator: branch on `contract.razorpay_reference_type` to call `fetch_payout_history` or `fetch_subscription_config`, then run the matching cross-check; verify with an integration test on a fixture contract producing the expected MismatchFlag set
- [x] 7.2 Extend `pipeline.services.run_pipeline(*, contract, from_stage=1)` to call `razorpay_integration.services.detect_mismatches` after stage 3, via a function-local import (per design.md's circular-import decision); verify with a test importing `pipeline.services` in isolation (razorpay_integration not pre-imported) without ImportError, and an end-to-end test confirming `run_pipeline(contract=contract)` produces MismatchFlag rows for a fixture contract with stages 1-3 pre-seeded

## 8. Selectors

- [x] 8.1 Implement `selectors.get_platform_records_for_contract(*, contract, record_type=None)`, `list_mismatch_flags_for_contract(*, contract)`, `get_latest_payout_records(*, contract, minimum=2)`; verify each with a dedicated selector test against factory-built rows

## 9. Guardrail verification

- [x] 9.1 Add a standing test asserting `client.py`'s production-path methods issue only GET requests against any live-data endpoint, run against a mocked transport that fails the test on any non-GET call; verify it passes
- [x] 9.2 Add a standing test asserting every MismatchFlag produced by a sample pipeline run has a non-null extracted_term_id and a fully resolvable reasoning chain (clause -> extracted_term -> platform_record or explicit missing-evidence -> description); verify it passes

## 10. Full verification

- [x] 10.1 Run the full test suite (`pytest`) and confirm no regressions in the `contracts` or `pipeline` apps
- [x] 10.2 Run the project's type checker across `razorpay_integration` and confirm zero errors
- [x] 10.3 Run `openspec validate add-razorpay-crosscheck --strict` and confirm it passes
