## Why

Every phase so far has been implemented and verified (373 tests passing across `core`, `contracts`, `pipeline`, `razorpay_integration`, `risk_scoring`, `reporting`, `evaluation`, `report_ui`). The project owner now wants a genuinely separate frontend — its own project, its own dependency tree, talking to the Django backend only over HTTP — rather than the Django-templates-only UI `add-report-ui` shipped. This supersedes that earlier decision explicitly (see design.md's ADR), not silently: `report_ui` stays exactly as built and tested; this change adds a second, independent consumer of the backend's data, and extends the backend's JSON API surface to fully support it.

**Non-goals**: this phase does not remove, modify the behavior of, or duplicate `report_ui`'s Django-templates views — they continue to serve the same routes unchanged. It does not change any pipeline, risk-scoring, Razorpay-integration, or evaluation behavior — only reads already-computed data. It does not add authentication/authorization (out of scope for the buildathon demo; both the new endpoints and the existing ones remain open, matching the project's current security posture).

## What Changes

- **Backend**: extend the `reporting` app's API surface with three new read-only endpoints — a contract list, a per-clause reasoning-chain endpoint, and a guardrail-verification endpoint — so a browser-based frontend has everything it needs without touching Django templates.
- **Backend refactor**: relocate `get_contract_reasoning_chain` and `scan_razorpay_guardrail` (plus their dataclasses) from `report_ui/selectors.py` to `reporting/selectors.py`. Both `report_ui` (templates) and the new API endpoints need these reads; `reporting` is this project's designated read-model app, and `reporting` must not depend on `report_ui` (that would invert the established phase ordering — `report_ui` depends on `reporting`, never the reverse). `report_ui/views.py` is updated to import from `reporting.selectors` instead; its own behavior and its 36 existing tests are unaffected.
- **Backend**: add a `list_contracts` selector to `contracts/selectors.py` (the one read this whole feature needs that no app currently provides).
- **Backend**: add CORS support (`django-cors-headers`) so a frontend running on a different origin/port can call the API in local development.
- **New**: a `frontend/` directory — a separate Vite + React + TypeScript project with its own `package.json`, calling the Django backend exclusively through `fetch` against the new and existing JSON endpoints. No server-side rendering, no shared build tooling with the Django project.

## Capabilities

### New Capabilities
- `api/contract-listing`: a JSON endpoint listing every ingested contract with enough summary data to populate a dashboard list.
- `api/reasoning-chain`: a JSON endpoint exposing a contract's full per-clause reasoning chain (classification → extraction → platform evidence → risk verdict), matching what `report_ui`'s reasoning-chain view already renders as HTML.
- `api/guardrail-verification`: a JSON endpoint exposing the live Razorpay-integration write-call guardrail scan result.
- `frontend/contract-dashboard`: the externally observable behavior of the new frontend application — what a user can see and do in the browser, independent of implementation.

### Modified Capabilities
(none declared — `report-ui/reasoning-chain-view` and `report-ui/guardrail-verification-view`'s own specs describe report_ui's HTML behavior, which is unchanged; the underlying selectors move, but that is an implementation detail invisible to those specs' scenarios. No change in this project has been archived yet, so there is nothing under `openspec/specs/` to declare a delta against regardless — same constraint noted in every prior change's proposal.)

## Impact

- **New code**: `frontend/` (separate Node/npm project); three new DRF views + serializers + URL routes in `reporting`; one relocated selector module's worth of functions moving from `report_ui` to `reporting`; one new selector in `contracts`.
- **New dependencies**: backend — `django-cors-headers`; frontend — `react`, `react-dom`, `react-router-dom`, `vite`, `typescript`, `vitest`, `@testing-library/react` (dev).
- **Infrastructure**: two separate local dev servers (`python manage.py runserver` on :8000, `npm run dev` on :5173 by default) — no reverse proxy or combined build for the buildathon demo; CORS handles cross-origin calls directly.
- **No impact** on `core`, `pipeline`, `razorpay_integration`, `risk_scoring`, `evaluation`, or any pipeline/scoring behavior — this change only reads already-persisted data through existing and new selectors.
