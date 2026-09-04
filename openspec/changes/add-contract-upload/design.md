## Context

`contracts.services.create_contract(*, raw_text, engagement_id, razorpay_reference_type, razorpay_reference_id, source_filename=None) -> Contract` already exists and already validates everything (raises `django.core.exceptions.ValidationError` with per-field messages). `pipeline.services.run_pipeline(*, contract, from_stage=1)` already exists, already orchestrates all six stages, and already leaves whatever it wrote in place if it raises partway through (this is exactly what was observed empirically in this project's own earlier sessions when the OpenAI provider rate-limited mid-run — partial `Clause`/`ExtractedTerm`/`RiskAssessment` rows remained intact). Neither function needs to change. `contracts` currently has no `urls.py`/real `views.py`; `pipeline` currently has no HTTP surface at all (CLI-only via `run_pipeline.py`).

## Goals / Non-Goals

**Goals:** a thin HTTP surface over the two existing service functions, with honest handling of the one thing that's already gone wrong in this exact project — a mid-pipeline provider failure — rather than assuming happy-path only.

**Non-Goals:** no async job queue (see proposal.md); no PDF/DOCX parsing; no change to any pipeline stage; no auth (matches this project's existing posture — every other endpoint is unauthenticated too).

## Decisions

**`contracts` app gains an HTTP surface: `views.py`, `serializers.py`, `urls.py`.**
- `contracts/serializers.py::ContractCreateSerializer(serializers.Serializer)`: `raw_text = CharField()`, `engagement_id = CharField()`, `razorpay_reference_type = ChoiceField(choices=RazorpayReferenceType.choices)`, `razorpay_reference_id = CharField()`, `source_filename = CharField(required=False, allow_null=True)`.
- `contracts/views.py::ContractCreateAPIView(APIView)`: `post()` validates via the serializer, calls `contracts.services.create_contract(**serializer.validated_data)`, catches `ValidationError` and returns it as a 400 with the field errors, otherwise returns `{"contract_id": str(contract.id)}` with 201. Thin per convention — no logic beyond validate-call-respond.
- `contracts/urls.py`: `path("contracts/create/", ContractCreateAPIView.as_view(), name="contract-create")`.
- Registered in `config/urls.py` as `path("", include("contracts.urls"))` alongside the existing `reporting.urls`/`report_ui.urls` includes (same root-level mount `reporting.urls` already uses, since neither defines a conflicting `contracts/create/` path — `reporting`'s existing `contracts/` routes are `contracts/`, `contracts/<uuid>/report/`, etc., none of which collide with `contracts/create/`).

**`pipeline` app gains an HTTP surface: `views.py`, `serializers.py`, `urls.py`.**
- `pipeline/views.py::AnalyzeContractAPIView(APIView)`: `post(self, request, contract_id)` — looks up the Contract (404 via the same `_get_contract_or_404`-style pattern `reporting/views.py` already established, duplicated here since `pipeline` should not import from `reporting`, which depends on `pipeline`, not the reverse), calls `pipeline.services.run_pipeline(contract=contract)` inside a `try/except Exception`. On success, returns `reporting.selectors.get_contract_report(contract=contract)` serialized via the *existing* `reporting.serializers.ContractReportSerializer` (imported, not duplicated — `pipeline` importing a read-only serializer from `reporting` is a one-way dependency in the safe direction, mirroring how `report_ui` already imports from `reporting`) with 200. On exception, returns 502 with `{"contract_id": ..., "error": str(exc), "partial_progress": True, "detail": "Pipeline stopped partway through. Whatever was already analyzed has been saved."}` — `partial_progress` is always `True` in the caught-exception branch since `run_pipeline` has already been observed in this project to leave real partial state on failure; this endpoint does not attempt to detect "how partial," only that some may exist, and points the caller at the report/reasoning-chain endpoints to see what's there.
- `pipeline/urls.py`: `path("contracts/<uuid:contract_id>/analyze/", AnalyzeContractAPIView.as_view(), name="contract-analyze")`.
- Registered in `config/urls.py` the same way as `contracts.urls`.

**Frontend: new `/upload` page.**
- `frontend/src/pages/UploadPage.tsx`: a form with a textarea (contract text) plus a file input restricted to `.txt` (`<input type="file" accept=".txt">`) that reads the selected file client-side via `FileReader` and populates the same textarea — no server-side file handling, no new backend dependency. Engagement id defaults to `upload-${Date.now()}`, razorpay_reference_type defaults to `"payout"`, razorpay_reference_id defaults to a placeholder like `manual-upload-${Date.now()}` — all three editable. A visible note above the submit button states the cost/duration expectation per the spec.
- `frontend/src/api/client.ts` gains `createContract(payload)` (POST to `/contracts/create/`) and `analyzeContract(contractId)` (POST to `/contracts/<id>/analyze/`), following the existing typed-`ApiError`-on-failure convention every other client function already uses.
- Submit flow: call `createContract` → on success, immediately call `analyzeContract` with the returned id, showing a distinct "Analyzing... this can take a few minutes" state (not the existing generic `LoadingState` component's default copy — a longer-running-operation variant, reusing the component with a custom message prop) → on `analyzeContract` success, `navigate` to `/contracts/<id>` → on `analyzeContract` failure, render the error message plus a link to `/contracts/<id>` (the partial result), reusing `ErrorState` with an additional link, not a new component.
- Nav: add "Upload" as a fourth link in `Layout.tsx`, after About.

## Risks / Trade-offs

- **[Risk]** A synchronous multi-minute HTTP request is fragile — a browser tab close, a network blip, or a reverse-proxy timeout in a real deployment would lose the in-flight request (though not the partial DB state, which is already persisted stage-by-stage). → **Mitigation**: accepted for this scope per the explicit non-goal (no task queue); the frontend's messaging sets this expectation honestly rather than pretending it's instant, and partial progress is never lost even if the request itself is.
- **[Risk]** No rate-limiting or abuse protection on an endpoint that spends real API quota per call. → **Mitigation**: accepted, consistent with every other endpoint in this project being unauthenticated and un-throttled — this is a buildathon demo, not a hardened public service; flagged here so it isn't mistaken for an oversight.
- **[Risk]** `pipeline/views.py` importing `reporting.serializers.ContractReportSerializer` is a new cross-app dependency. → **Mitigation**: direction is safe (`pipeline` → `reporting`, and `reporting` already depends on `pipeline`'s selectors, not the reverse — no cycle), and it avoids duplicating the report shape a second time; the alternative (returning a bare `{"contract_id": ...}` and making the frontend fetch the report separately) was considered and rejected as an unnecessary extra round-trip when the view already has everything needed to build the response in one call.

## Migration Plan

No models, no migrations. Rollout: (1) `contracts` create endpoint + tests, (2) `pipeline` analyze endpoint + tests (depends on 1 only for manual testing convenience, not a code dependency), (3) frontend page once both endpoints are stable and their real response shapes are confirmed by reading the actual serializer output, not assumed from this doc.
