## 1. Models and migrations

- [ ] 1.1 Add `TRANSFER = "transfer", "Transfer"` to `contracts.models.RazorpayReferenceType`; generate and hand-review the migration; verify with `python manage.py makemigrations --check` and `python manage.py migrate` against a fresh test database
- [ ] 1.2 Add `TRANSFER = "transfer", "Transfer"` to `razorpay_integration.models.PlatformRecordType`; generate and hand-review the migration; verify the same way
- [ ] 1.3 Verify `python manage.py check` passes with both new choices loaded

## 2. Read-only Razorpay client

- [ ] 2.1 Implement `RazorpayConnector.fetch_transfers(*, recipient_settlement_id)` in `razorpay_integration/client.py`, mirroring `fetch_payouts`'s GET-with-fallback shape against `GET /v1/transfers`; verify with a mocked-SDK test asserting the correct path and params, per "Transfer records fetched via read-only GET calls"
- [ ] 2.2 Extend `test_client.py`'s existing AST source-scan guardrail test run (no change to the scan itself) with an assertion that `fetch_transfers` is present and reachable, plus a raw-`requests`-fallback test mirroring `fetch_token`'s fallback test
- [ ] 2.3 Extend `test_guardrails.py::test_connector_only_ever_dispatches_get_requests` to also call `fetch_transfers` against the mocked transport, asserting only a GET is dispatched

## 3. Route cross-check logic (route-transfer-crosscheck spec)

- [ ] 3.1 Implement `services.fetch_transfer_history(*, contract)` persisting one `PlatformRecord(record_type=transfer)` per fetched Transfer, no-op for a non-transfer-referenced Contract; verify with a mocked-API test asserting >=2 transfers produce matching PlatformRecord rows with correct payload, per "Transfer records fetched via read-only GET calls" and "Third path selected by transfer-referenced contracts"
- [ ] 3.2 Rename `_create_missing_platform_evidence_flag`'s `payout_record_count` keyword argument to `record_count`, updating its one existing call site in `_run_payout_crosscheck`; verify `test_payout_crosscheck.py`'s existing missing_platform_evidence assertions still pass unchanged
- [ ] 3.3 Implement `_is_percentage_term(term)` (unit in `{"percent", "percentage", "pct", "%"}`); verify with unit tests for each recognized unit spelling and for a non-percentage unit returning False
- [ ] 3.4 Implement `_run_route_crosscheck(*, contract)`: route each payout_frequency term through `_is_percentage_term`/`_is_cadence_term` (→ trigger_condition_unverifiable) or flat-amount comparison against the empirical Transfer amount (reusing `_compute_empirical_amount` and `_evaluate_amount_term` unchanged); verify with tests covering a within-tolerance flat amount (no flag), an over-tolerance flat amount (amount_mismatch), per "Amount mismatch detection against a configured tolerance"
- [ ] 3.5 Implement missing_platform_evidence flagging when fewer than 2 Transfer records exist, via the renamed shared helper; verify with tests for 0 and 1 transfer each producing a missing_platform_evidence MismatchFlag with platform_record null, per "Missing platform evidence when insufficient Transfer history exists"
- [ ] 3.6 Verify a percentage-denominated payout_frequency term produces trigger_condition_unverifiable, not amount_mismatch or missing_platform_evidence, and that no Transfer-amount comparison is attempted against it, per "Percentage-based splits are out of scope for Route cross-checking"
- [ ] 3.7 Verify a cadence-shaped payout_frequency term (a time interval, no flat amount) produces trigger_condition_unverifiable on the route path, per the same requirement's second scenario
- [ ] 3.8 Verify no generated description or persisted string in the route path contains the phrase "split rule," "split configuration," or equivalent, per "No claim of a Route split-rule configuration" — a grep-based test over generated description output, mirroring the payout path's existing "no schedule config" test
- [ ] 3.9 Verify zero `core.llm_client` calls occur for a route comparison that does not deterministically produce a MismatchFlag, per "Deterministic mismatch classification precedes any LLM involvement"
- [ ] 3.10 Wire the third branch into `services.detect_mismatches` (`razorpay_reference_type == TRANSFER` → `fetch_transfer_history` then `_run_route_crosscheck`); verify with an integration test on a fixture contract producing the expected MismatchFlag set, and a test confirming `pipeline.services.run_pipeline` needs no code change to reach it (stage-4 call is already unconditional)

## 4. Fixtures (test-mode seeding)

- [ ] 4.1 Implement `fixtures.seed_transfer(*, payment_id, account, amount_paise, on_hold=False, client=None)` as a POST-only, test-mode-only helper following `seed_payout`'s pattern; verify `test_fixtures_isolation.py`'s existing assertion (`fixtures` absent from `detect_mismatches`'s transitive import graph) still passes with the new function present

## 5. Tests and selectors

- [ ] 5.1 Extend `razorpay_integration/tests/factories.py`'s `PlatformRecordFactory` usage (or add a thin transfer-payload default) so route-path tests can build `PlatformRecord(record_type=transfer, ...)` rows without duplicating factory boilerplate
- [ ] 5.2 Add `razorpay_integration/tests/test_route_crosscheck.py` mirroring `test_payout_crosscheck.py`'s structure, covering every scenario in specs/razorpay-integration/route-transfer-crosscheck/spec.md
- [ ] 5.3 Verify `selectors.get_platform_records_for_contract(*, contract, record_type=PlatformRecordType.TRANSFER)` returns the expected rows via a dedicated selector test (no code change to selectors.py itself — this is a coverage-only test per design.md's "selectors.py needs no change" decision)
- [ ] 5.4 Extend `test_pipeline_integration.py` with an end-to-end case: a transfer-referenced fixture contract with stages 1-3 pre-seeded produces the expected route-path MismatchFlag rows when `run_pipeline(contract=contract)` runs

## 6. Frontend reference-type option

- [ ] 6.1 Add `"transfer"` to `frontend/src/api/types.ts`'s `RazorpayReferenceType` union
- [ ] 6.2 Add a `transfer: "Transfer (Route)"` entry to `frontend/src/utils/format.ts`'s `RAZORPAY_REFERENCE_TYPE_LABELS`
- [ ] 6.3 Add a third `<option value="transfer">Transfer (Route)</option>` to `frontend/src/pages/UploadPage.tsx`'s reference-type select
- [ ] 6.4 Update/extend any existing frontend tests that enumerate `RazorpayReferenceType` values (e.g. `UploadPage` tests) to cover the new option; verify `npm run build` succeeds with zero TypeScript errors

## 7. Full verification

- [ ] 7.1 Run the full backend test suite (`pytest`) and confirm no regressions in `contracts`, `pipeline`, or the existing payout/subscription paths of `razorpay_integration`
- [ ] 7.2 Run the project's type checker across `razorpay_integration` and confirm zero errors
- [ ] 7.3 Run `npm run build && npm run test` in `frontend/` and confirm all green
- [ ] 7.4 Manually verify Route is actually enabled on the demo Razorpay account (dashboard → Route, or a sandbox `GET /v1/transfers` call) before relying on this capability for a live demo, per design.md's KYB/approval risk
- [ ] 7.5 Run `openspec validate add-razorpay-route-crosscheck --strict` and confirm it passes
