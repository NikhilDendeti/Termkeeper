## 1. Backend — selector and serializer

- [ ] 1.1 Extend `reporting.selectors.ClauseReasoningChain` with `verified_platform_records: list[PlatformRecord]` and the computation logic in `get_contract_reasoning_chain`, per design.md, with tests for all three spec scenarios: matching contract shows confirmed evidence, no platform data ever checked stays empty, a mismatched clause does not also show confirmed evidence
- [ ] 1.2 Add `PlatformRecordSerializer` and wire `verified_platform_records` into `ClauseReasoningChainSerializer`, with a test asserting the field appears correctly in a live `GET /contracts/<id>/reasoning-chain/` response
- [ ] 1.3 Run the full backend suite (`pytest -q`) and confirm every previously-passing test still passes

## 2. UI updates (parallel — independent of each other)

- [ ] 2.1 Update `report_ui`'s reasoning-chain template with the three-way branch (mismatch / confirmed / no evidence), with a test asserting the confirmed-evidence block renders for a clause with `verified_platform_records` and not for one without
- [ ] 2.2 Update `frontend/src/api/types.ts` (new `PlatformRecord` interface + field) and `frontend/src/pages/ContractDetailPage.tsx` with the same three-way branch, styled distinctly (not reusing the mismatch's color), with a component test for the confirmed-evidence render path; verify `npm run build` succeeds with zero TypeScript errors

## 3. Verification

- [ ] 3.1 Run the full backend suite and `npm run build && npm run test` in `frontend/`, confirm all green
- [ ] 3.2 Manually verify against the live seeded demo data: contract 3 (`demo-fair-control`) now shows confirmed platform evidence on its payment_schedule clause instead of "No platform evidence available"; contract 1 (`demo-milestone-drift`, Razorpay disabled) still correctly shows "No platform evidence available" everywhere; contract 2's mismatched clause still shows the mismatch, not confirmed evidence
- [ ] 3.3 Run `openspec validate add-confirmed-platform-evidence --strict`
