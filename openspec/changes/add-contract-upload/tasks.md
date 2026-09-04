## 1. Backend — contract creation endpoint

- [ ] 1.1 Implement `contracts/serializers.py::ContractCreateSerializer` and `contracts/views.py::ContractCreateAPIView`, wire `contracts/urls.py`, register in `config/urls.py`, with tests covering: valid submission creates a Contract and returns its id (201), a request missing each required field is rejected (400) with a field-specific error, and no Contract is created on rejection (spec: Contract creation endpoint)
- [ ] 1.2 Write a test asserting this endpoint and the existing `ingest_contract` management command produce equivalent Contract state for the same input (spec: Endpoint reuses existing validation, does not duplicate it)
- [ ] 1.3 Run `pytest contracts/ -q` and the full suite, confirm all passing

## 2. Backend — pipeline analyze endpoint

- [ ] 2.1 Implement `pipeline/serializers.py` (if needed for the response) and `pipeline/views.py::AnalyzeContractAPIView`, wire `pipeline/urls.py`, register in `config/urls.py`, with a test asserting a successful analysis returns the aggregate report shape (spec: Synchronous pipeline trigger endpoint) and a test asserting an unknown contract id returns 404 (spec: Unknown contract returns a clear error)
- [ ] 2.2 Write a test that mocks `pipeline.services.run_pipeline` to raise partway through (after some rows are persisted by the mock/fixture setup) and asserts the endpoint returns a structured error naming the contract id and `partial_progress: true`, and that no already-persisted rows are deleted or altered (spec: Mid-run failure is reported, not silently swallowed or a bare server error)
- [ ] 2.3 Run `pytest pipeline/ -q` and the full suite, confirm all passing

## 3. Frontend — upload page

- [ ] 3.1 Add `createContract` and `analyzeContract` to `frontend/src/api/client.ts` and their types to `frontend/src/api/types.ts`, matching the real backend response shapes from tasks 1-2 (read the actual serializers, not this doc, before finalizing types), with client tests mirroring the existing per-function mock-fetch convention
- [ ] 3.2 Implement `frontend/src/pages/UploadPage.tsx`: form with textarea + `.txt` file-read-to-textarea, defaulted/editable engagement and Razorpay fields, the cost/duration notice, submit flow (create → analyze → navigate on success, error state with a link to the partial result on failure), routed at `/upload` and linked from `Layout.tsx`'s nav, with tests covering: defaults present, successful submit navigates to the contract detail page, and a failed analyze shows the error plus a working link to the partial result (spec: frontend/upload-page, all five requirements)
- [ ] 3.3 Verify `npm run build` (zero TS errors) and `npm run test` (all passing) in `frontend/`

## 4. Verification

- [ ] 4.1 Run the full backend suite (`pytest -q`) and confirm every previously-passing test still passes plus this change's new ones
- [ ] 4.2 Run `mypy` across `contracts` and `pipeline`, confirm zero errors
- [ ] 4.3 Manually verify end to end against the live dev servers: submit a short real contract through `/upload` (using a real `OPENAI_API_KEY` if quota allows, or documenting that this specific manual step is blocked by quota and needs to be done once quota is available) and confirm it lands on the contract detail page with real analysis
- [ ] 4.4 Run `openspec validate add-contract-upload --strict`
