## Context

See proposal.md - Why. `reporting`, `report_ui`, `contracts`, `pipeline`, `risk_scoring`, `razorpay_integration`, and `evaluation` already exist and are fully tested (373 passing tests). This change adds a read-only JSON surface on top of what's already there, plus a wholly separate frontend project. Nothing here changes pipeline, scoring, or Razorpay-integration behavior.

## Goals / Non-Goals

**Goals:**
- One read-model app (`reporting`) owns every non-trivial read this project exposes, whether the consumer is a Django template (`report_ui`) or a JSON API (this change, and the new frontend). No read logic is duplicated between the two consumers.
- The frontend is a genuinely separate project — its own `package.json`, its own dependency tree, zero shared build tooling with Django — connected only over HTTP.
- Every new DRF view stays thin (per project convention): look up the Contract (404 on a miss), call one selector, serialize, return. No business logic in views.

**Non-Goals:**
- No authentication/authorization on any endpoint, existing or new — matches the project's current posture; out of scope for the buildathon demo.
- No server-side rendering, no Next.js-style framework, no shared code generation between backend and frontend (e.g. no OpenAPI-generated client) — a small hand-written TypeScript API client is enough at this scale and keeps the two projects genuinely independent.
- No production deployment/reverse-proxy configuration — local dev only (`runserver` + `vite dev`), CORS handles the cross-origin calls.

## Decisions

**ADR — supersedes `add-report-ui`'s "Django-only end to end" decision.** That design.md chose Django-templates specifically to avoid a second project. The project owner has since explicitly asked for a genuinely separate frontend and backend. Rather than silently reversing the earlier ADR, this one records the reversal directly: `report_ui` is not removed or deprecated — its templates, views, and 36 tests continue to serve their existing routes unchanged, and it remains the reference implementation of "what the reasoning chain / audit log / guardrail views should show," which the new frontend must match. Alternative considered: retire `report_ui` and replace it outright. Rejected — it's already built and tested, and removing verified work to satisfy a stack preference (rather than a behavior change) is not this project's convention (see openspec/config.yaml on avoiding unnecessary rewrites).

**Refactor: relocate the reasoning-chain and guardrail-scan reads from `report_ui.selectors` to `reporting.selectors`.** Both currently live in `report_ui/selectors.py` (`get_contract_reasoning_chain`, `ClauseReasoningChain`, `scan_razorpay_guardrail`, `GuardrailScanResult`, `GuardrailViolation`, and their private helpers). `reporting` needs them for the new API endpoints. `reporting` must not import from `report_ui` — `report_ui` depends on `reporting`, established in `add-report-ui`'s own design (report_ui/views.py already imports `reporting.selectors.get_contract_report`); the reverse would be a backward, phase-inverting dependency. So the functions move to `reporting/selectors.py`, and `report_ui/views.py`'s two call sites are updated to `from reporting import selectors as reporting_selectors` (already imported there for the report view) instead of importing from its own `selectors.py`. `report_ui/selectors.py` keeps nothing after this move — delete the file only if nothing else in it is used; check before deleting. No behavior changes; `report_ui`'s existing 36 tests must pass unmodified except for import-path updates in whichever test files patch these functions (e.g. a test patching `report_ui.selectors.scan_razorpay_guardrail` now patches `reporting.selectors.scan_razorpay_guardrail`, and `report_ui/views.py`'s call site changes accordingly).

**New selector: `contracts/selectors.py::list_contracts() -> QuerySet[Contract]`** — ordered `-created_at`. The one read nothing currently provides.

**Extend `reporting` app:**
- `reporting/selectors.py` gains (moved, not new logic): `get_contract_reasoning_chain(*, contract: Contract) -> list[ClauseReasoningChain]`, `scan_razorpay_guardrail(*, scanned_paths=None, excluded_paths=None) -> GuardrailScanResult`, plus a new `list_contract_summaries() -> list[ContractSummary]` (a new small dataclass: contract_id, engagement_id, razorpay_reference_type, overall_risk_score, needs_human_review_count, created_at) built by calling `list_contracts()` and `get_contract_report()` per contract.
- `reporting/serializers.py` gains: `ContractSummarySerializer`, `ClauseReasoningChainSerializer` (nesting the existing shapes: clause fields, extracted terms, `PlatformMismatchSerializer`-shaped evidence, a nullable risk-assessment sub-serializer), `GuardrailViolationSerializer`, `GuardrailScanResultSerializer`.
- `reporting/views.py` gains three thin `APIView` classes: `ContractListAPIView` (`GET /contracts/`), `ContractReasoningChainAPIView` (`GET /contracts/<uuid:contract_id>/reasoning-chain/`), `GuardrailVerificationAPIView` (`GET /guardrail-verification/`) — each following the existing `_get_contract_or_404` pattern already in the file.
- `reporting/urls.py` gains the three routes above, following the existing two entries' naming convention.

**CORS:** add `django-cors-headers` to `INSTALLED_APPS`/`MIDDLEWARE` (as `corsheaders`, middleware placed before `CommonMiddleware` per the package's own requirement). `CORS_ALLOWED_ORIGINS` read from a new `DJANGO_CORS_ALLOWED_ORIGINS` env var (comma-separated), defaulting to `http://localhost:5173,http://127.0.0.1:5173` (Vite's default dev port) in `config/settings/local.py` only — `production.py` requires the env var to be set explicitly, no default, matching the existing `DJANGO_ALLOWED_HOSTS` pattern in that file.

**Frontend: Vite + React + TypeScript, no framework beyond `react-router-dom`.**
- `frontend/package.json` — separate project, own `node_modules`, no dependency on anything in the Django project.
- `frontend/src/api/types.ts` — TypeScript interfaces mirroring every DRF serializer above field-for-field (e.g. `ContractSummary`, `ClauseReasoningChain`, `RiskAssessment | null`, `GuardrailScanResult`).
- `frontend/src/api/client.ts` — a small typed fetch wrapper: `getContracts()`, `getContractReport(id)`, `getContractReasoningChain(id)`, `getContractAuditTrail(id)`, `getGuardrailStatus()`. Base URL from `import.meta.env.VITE_API_BASE_URL`, defaulting to `http://localhost:8000`. Every function throws a typed `ApiError` (status + message) on a non-2xx response or a network failure, so pages can render the error-state requirement from the spec rather than crash.
- `frontend/src/pages/`: `ContractListPage.tsx` (spec: Contract list is the landing view), `ContractDetailPage.tsx` (spec: Contract detail shows the full reasoning chain + Audit trail is reachable per contract — tabs or sections within one page, not a design requirement either way, implementer's call), `GuardrailPage.tsx` (spec: Guardrail status is visible).
- `frontend/src/components/`: `SeverityBadge.tsx` (color-codes low/medium/high/critical/needs_human_review, reusing the same five-value taxonomy `risk_scoring` already defines — implementer hardcodes the five string values, no need to fetch a taxonomy endpoint for five constants), `Layout.tsx` (nav: Contracts, Guardrail Status), `LoadingState.tsx`, `ErrorState.tsx` (shared by every page per the spec's Network and error states requirement).
- Routing: `react-router-dom`, three routes (`/`, `/contracts/:id`, `/guardrail`).
- Testing: Vitest + `@testing-library/react`. `api/client.ts` tested against a mocked `fetch`; each page gets at least one render test (loading → data, and loading → error, using a mocked client).

## Risks / Trade-offs

- **[Risk]** Relocating functions out of `report_ui/selectors.py` touches a previously "done" phase 5 file. → **Mitigation**: scoped to exactly the two functions/dataclasses this change needs moved, verified by re-running `report_ui`'s full existing test suite (36 tests) after the move with zero behavior change, only import-path updates where a test patches the relocated function.
- **[Risk]** No auth on the new endpoints means anyone who can reach the backend can read every contract's report. → **Mitigation**: accepted, consistent with every existing endpoint's current posture (also unauthenticated) — this is a buildathon demo project, not a decision unique to this change; flagged here so it isn't mistaken for an oversight.
- **[Risk]** CORS defaults are permissive in local dev (`local.py` hardcodes the Vite port). → **Mitigation**: `production.py` has no default and requires the env var explicitly, mirroring the existing `DJANGO_ALLOWED_HOSTS` pattern — the permissive default is local-only.
- **[Risk]** Two frontends (`report_ui` templates and the new React app) can drift out of sync in what they show. → **Mitigation**: accepted for now — `report_ui` remains the reference behavior every new-frontend spec scenario is checked against; if one is retired later, that's a separate, explicit future change, not silently decided here.

## Migration Plan

No database migration (no new models). Rollout order: (1) move the two selector functions and update `report_ui`'s imports, confirm its existing tests still pass; (2) add the new `contracts` selector; (3) add the three `reporting` endpoints + CORS; (4) scaffold and build the frontend against the now-stable API. Rollback: the relocation is a pure move (git-revertable); the three new endpoints and CORS config can be removed without affecting `report_ui` or any other app, since nothing else depends on them.
