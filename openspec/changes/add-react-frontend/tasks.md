## 1. Backend refactor — relocate reasoning-chain and guardrail-scan reads

- [ ] 1.1 Move `get_contract_reasoning_chain`, `ClauseReasoningChain`, `scan_razorpay_guardrail`, `GuardrailScanResult`, `GuardrailViolation`, and their private helpers from `report_ui/selectors.py` to `reporting/selectors.py`, updating imports in both files, and verify `manage.py check` passes
- [ ] 1.2 Update `report_ui/views.py`'s two call sites to import the relocated functions from `reporting.selectors`, and update any test that patches them (e.g. `@patch("report_ui.selectors.scan_razorpay_guardrail")` → `@patch("reporting.selectors.scan_razorpay_guardrail")`), then verify the full pre-existing `report_ui/` test suite (36 tests) still passes unchanged in behavior
- [ ] 1.3 Run the full pre-existing suite (`pytest -q`) and verify all 373 previously-passing tests still pass after the move

## 2. Backend — contract list read

- [ ] 2.1 Implement `contracts/selectors.py::list_contracts() -> QuerySet[Contract]` ordered `-created_at`, with a unit test asserting newest-first ordering and the empty-project case

## 3. Backend — reporting: summaries and serializers

- [ ] 3.1 Implement `reporting/selectors.py::list_contract_summaries() -> list[ContractSummary]` (new dataclass: contract_id, engagement_id, razorpay_reference_type, overall_risk_score, needs_human_review_count, created_at), with a test asserting overall_risk_score is null for a contract with no scored clauses (spec: Summary reflects current pipeline state)
- [ ] 3.2 Implement `reporting/serializers.py::ContractSummarySerializer`, `ClauseReasoningChainSerializer` (nesting extracted terms, platform evidence, nullable risk assessment), `GuardrailViolationSerializer`, `GuardrailScanResultSerializer`

## 4. Backend — new endpoints

- [ ] 4.1 Implement `ContractListAPIView` (`GET /contracts/`) in `reporting/views.py`, thin per convention, with tests covering the newest-first-ordering and empty-list scenarios (spec: api/contract-listing)
- [ ] 4.2 Implement `ContractReasoningChainAPIView` (`GET /contracts/<uuid:contract_id>/reasoning-chain/`), with tests covering: every clause included regardless of state, empty platform-evidence list (not omitted), null risk_assessment for an unscored clause, and 404 on an unknown contract id (spec: api/reasoning-chain)
- [ ] 4.3 Implement `GuardrailVerificationAPIView` (`GET /guardrail-verification/`), with a test asserting two consecutive requests each independently compute the scan (spec: api/guardrail-verification, "reflects current source, not a cached claim")
- [ ] 4.4 Add all three routes to `reporting/urls.py` following the existing naming convention, and verify `manage.py check` plus a manual `runserver` smoke request against each new route returns the expected shape

## 5. Backend — CORS

- [ ] 5.1 Add `django-cors-headers` to dependencies, `INSTALLED_APPS`, and `MIDDLEWARE` (before `CommonMiddleware`); add `CORS_ALLOWED_ORIGINS` to `config/settings/base.py` read from `DJANGO_CORS_ALLOWED_ORIGINS`, with `local.py` defaulting to the Vite dev ports and `production.py` requiring the env var with no default
- [ ] 5.2 Verify with a manual cross-origin request (e.g. `curl -H "Origin: http://localhost:5173" -I http://localhost:8000/contracts/`) that the response carries `Access-Control-Allow-Origin`

## 6. Frontend — project scaffold

- [ ] 6.1 Scaffold `frontend/` as a Vite + React + TypeScript project (`npm create vite@latest`), with its own `package.json`, `tsconfig.json`, `.gitignore` (node_modules, dist), `.env.example` (`VITE_API_BASE_URL=http://localhost:8000`), and verify `npm install && npm run build` succeeds with zero TypeScript errors on the untouched scaffold
- [ ] 6.2 Add `react-router-dom` and set up the three-route router (`/`, `/contracts/:id`, `/guardrail`) in `App.tsx`, verify `npm run build` still succeeds
- [ ] 6.3 Add Vitest + `@testing-library/react` as dev dependencies with a working test config, and verify `npm run test` runs (even with zero tests yet) with no configuration errors

## 7. Frontend — API client

- [ ] 7.1 Write `frontend/src/api/types.ts` mirroring every new/existing DRF serializer field-for-field
- [ ] 7.2 Write `frontend/src/api/client.ts` (`getContracts`, `getContractReport`, `getContractReasoningChain`, `getContractAuditTrail`, `getGuardrailStatus`) with a typed `ApiError` thrown on non-2xx or network failure, and unit tests mocking `fetch` for a success case and a failure case per function

## 8. Frontend — shared components

- [ ] 8.1 Implement `SeverityBadge.tsx` covering all five severity values (low/medium/high/critical/needs_human_review) with visibly distinct styling for needs_human_review vs. any scored severity (spec: Needs-human-review clause visibly distinct), with a render test per value
- [ ] 8.2 Implement `Layout.tsx` (nav: Contracts, Guardrail Status), `LoadingState.tsx`, `ErrorState.tsx`, with a render test for each

## 9. Frontend — pages

- [ ] 9.1 Implement `ContractListPage.tsx`: fetches and renders the contract list, shows `LoadingState` while in flight, `ErrorState` on failure, and an explicit empty state when the list is empty (spec: Contract list is the landing view), with tests for the loading→data and loading→error transitions using a mocked API client
- [ ] 9.2 Implement `ContractDetailPage.tsx`: fetches and renders a contract's reasoning chain in sequence order (every clause, including needs_human_review and not-yet-scored clauses) and its audit trail (stage, prompt version, model name, latency, and an inspectable raw response), with tests covering a clause with no platform evidence, a clause not yet risk-scored, and an audit entry's raw response being viewable (spec: Contract detail shows the full reasoning chain, Audit trail is reachable per contract)
- [ ] 9.3 Implement `GuardrailPage.tsx`: fetches and renders the guardrail-verification result as an unambiguous pass/fail with scanned files and violation evidence, with tests for both a passing and a failing mocked result (spec: Guardrail status is visible)

## 10. Verification

- [ ] 10.1 Run `npm run build` and `npm run test` in `frontend/` and verify both succeed with zero errors
- [ ] 10.2 Start the Django backend (`runserver`) and the frontend (`npm run dev`) together, seed at least one contract through the existing pipeline/fixtures, and manually verify in a browser (or via a scripted fetch) that the contract list, contract detail (reasoning chain + audit trail), and guardrail page all render real data from the live backend, not just mocked-test data
- [ ] 10.3 Run the full backend suite (`pytest -q`) and confirm it still reports all previously-passing tests plus this change's new tests, all passing, and run `openspec validate add-react-frontend --strict` before requesting archive
