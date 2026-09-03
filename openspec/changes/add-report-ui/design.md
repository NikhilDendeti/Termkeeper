## Context

See proposal.md - Why. Phase 1 (`add-django-foundation`) provides `Contract`, `Clause`, `ExtractedTerm`, `AuditLogEntry` and their selectors. Phase 2 (`add-razorpay-crosscheck`) and phase 3 (`add-risk-scoring-report`) have not been written as OpenSpec changes yet — only their scope is fixed by the project's five-phase build order. This design therefore states, as explicit forward-reference assumptions, the phase 2/3 selector shapes `report_ui` depends on. These assumptions are scoped narrowly (function name, args, return shape) precisely so that when `add-razorpay-crosscheck` and `add-risk-scoring-report` are actually written, reconciling them against this document is a small, mechanical check rather than a redesign.

**Forward-reference assumptions** (to be confirmed/reconciled when phases 2 and 3 are written):
- `razorpay_integration.models.PlatformRecord` and `razorpay_integration.models.MismatchFlag` (phase 2) exist per-clause or per-extracted-term, and a selector `razorpay_integration.selectors.get_platform_evidence_for_clause(*, clause: Clause) -> ClausePlatformEvidence | None` returns a small dataclass bundling the matching `PlatformRecord`/`MismatchFlag` (or `None` if no platform evidence exists for that clause).
- `razorpay_integration`'s production-path modules are `razorpay_integration/client.py` and `razorpay_integration/services.py`; its test-mode fixture/demo-seeding module (isolated from the production path per the project's guardrail) is `razorpay_integration/testmode_fixtures.py`.
- `risk_scoring.models.RiskAssessment` (phase 3) exists per clause (or per extracted term), and phase 3's stage 6 "pure-query aggregate report" is exposed as `risk_scoring.selectors.get_contract_report(*, contract: Contract) -> ContractReport`, a dataclass whose nested per-clause entries already carry the classification, extracted term, platform evidence, and risk verdict (or the appropriate `needs_human_review`/empty-state markers) needed for the reasoning-chain view. Phase 3's own DRF report endpoint is expected to call this same selector, so `report_ui` reuses it rather than re-deriving the aggregate.

## Goals / Non-Goals

**Goals:**
- Make every reasoning-chain element, audit-log entry, and the no-write-calls guardrail concretely browsable by a human reviewer, with no step requiring direct database or API access.
- Keep `report_ui` strictly a rendering layer: views call selectors and pass their return values to templates; all aggregation, scanning, and interpretation logic lives in selector functions, never in a view body or a template tag beyond pure formatting.
- Make the `needs_human_review` state impossible to visually confuse with a scored severity, verifiable by both a human glance and an automated text-content check.
- Make the guardrail claim ("no write calls against live data") independently checkable by a reviewer, not just assertable in documentation.

**Non-Goals:**
- No new models, no new DRF endpoints, no new external dependency.
- No authentication/authorization on these views — single-tenant buildathon demo scope; if this ships beyond the demo, access control is a follow-up change.
- No client-side JavaScript framework or build step — any interactivity (expand/collapse) uses native `<details>`/`<summary>` elements, consistent with the project's no-separate-Node-frontend decision.
- No attempt to catch every conceivable way a write call could be obscured (e.g., fully dynamic method dispatch via `getattr` with a runtime-computed string) — scope is stated explicitly in Risks below.

## Decisions

**New Django app: `report_ui`** (no models — HackSoft convention still applies: no models means no `models.py` content beyond the default empty module).

- `views.py` (thin; each view's only logic is arg parsing, a selector call, and a template render — no aggregation, no formatting decisions beyond what the template layer does):
  - `contract_report_view(request: HttpRequest, contract_id: UUID) -> HttpResponse` — calls `contracts.selectors.get_contract(*, contract_id=contract_id)` and `risk_scoring.selectors.get_contract_report(*, contract=contract)`; renders `report_ui/contract_report.html` with `{"contract": contract, "report": report}`.
  - `contract_audit_log_view(request: HttpRequest, contract_id: UUID) -> HttpResponse` — calls `contracts.selectors.get_contract(*, contract_id=contract_id)` and `pipeline.selectors.get_audit_trail(*, contract=contract)`; renders `report_ui/contract_audit_log.html` with `{"contract": contract, "entries": entries}`.
  - `guardrail_verification_view(request: HttpRequest) -> HttpResponse` — calls `report_ui.selectors.scan_razorpay_guardrail()`; renders `report_ui/guardrail_verification.html` with `{"result": result}`.
- `selectors.py` (read-only; the guardrail scan reads the filesystem rather than the database, but it is a pure read with no side effect, so it belongs here rather than in a `services.py` this app has no other reason to have):
  - `scan_razorpay_guardrail(*, scanned_paths: tuple[Path, ...] | None = None, excluded_paths: tuple[Path, ...] | None = None) -> GuardrailScanResult` — defaults `scanned_paths` to `razorpay_integration/client.py` and `razorpay_integration/services.py`, and `excluded_paths` to `razorpay_integration/testmode_fixtures.py`; parses each scanned file with `ast.parse`, walks `ast.Call` nodes, and flags any call whose attribute name is in a fixed write-verb set (`{"post", "put", "patch", "delete"}`) or matches a configured list of known SDK write-method names. Returns a `GuardrailScanResult` dataclass: `passed: bool`, `scanned_files: list[str]`, `violations: list[GuardrailViolation]` where `GuardrailViolation` is `file: str, line: int, matched_call: str`. Never imports or executes the scanned modules — parses source text only, so the scan itself makes no network calls.
- `management/commands/verify_guardrail.py` — calls the same `scan_razorpay_guardrail()`, prints the file list and result, exits with status 1 if `passed` is `False` (for CI use alongside the page).
- `templatetags/report_ui_extras.py` — `pretty_json(value: dict) -> str` template filter (formats a JSON-serializable dict with indentation for the audit-log raw-response view); pure formatting, no business logic.
- `urls.py`:
  - `contracts/<uuid:contract_id>/report/` -> `contract_report_view`, name `contract_report`
  - `contracts/<uuid:contract_id>/audit-log/` -> `contract_audit_log_view`, name `contract_audit_log`
  - `guardrail/` -> `guardrail_verification_view`, name `guardrail_verification`
  - included from the project's `config/urls.py` under an `report/` prefix.
- Templates: `report_ui/templates/report_ui/base.html` (shared layout, loads `report_ui/css/report.css`), `contract_report.html`, `contract_audit_log.html`, `guardrail_verification.html`. `contract_report.html` links to `contract_audit_log.html` for the same contract, and both link to `guardrail_verification.html`, so a reviewer can move between the three without leaving the app.

**Follows the HackSoft-style service/selector convention; no deviation.** `report_ui` has no writes, so it has no `services.py`; its one non-trivial read (`scan_razorpay_guardrail`) lives in `selectors.py` per convention. Views contain no business logic beyond a selector call and a render — confirmed for all three views above.

**Reuse phase 3's `get_contract_report` aggregate selector rather than re-deriving the reasoning chain in `report_ui`.** Alternative considered: have `report_ui`'s view join across `Clause`, `ExtractedTerm`, platform-evidence, and `RiskAssessment` itself. Rejected — that duplicates stage 6's aggregate-report logic in two places (phase 3's DRF response and this phase's template context), which risks the two drifting out of sync, and a view assembling multi-model joins is business logic, violating the thin-views convention this project enforces everywhere else.

**Guardrail scanner is AST-based, not regex-based.** Alternative considered: `grep`/regex over the source text for `.post(`, `.patch(`, etc. Rejected as the sole mechanism — regex risks both false positives (a string literal or comment containing "post") and false negatives (a call split across lines); `ast.parse` + `ast.walk` over `Call` nodes gives an accurate call name and line number per match.

**Guardrail scan runs live on every page/command invocation, never cached or stored.** Alternative considered: persist scan results to a model, refreshed on deploy. Rejected — this phase adds no models, and a stored result could go stale between a fix and the next deploy, undermining the "prove it, don't assert it" goal the spec requires (Requirement: Result reflects the current state of the source).

**No DRF serializers in this phase.** Views build a plain dict template context directly from selector return values (model instances, querysets, and phase 3's `ContractReport` dataclass); Django's template engine renders it. Consistent with the project's decision that the report UI is server-rendered templates only, with no separate Node frontend and no need for a JSON contract between a frontend and this data.

**Static assets: plain CSS, no build step.** `report_ui/static/report_ui/css/report.css` is hand-written CSS linked via `{% load static %}` / `{% static %}` in `base.html`; no Sass/PostCSS/bundler is introduced, matching the project's no-Node-frontend decision for the entire report-UI phase. The `needs_human_review` treatment is a dedicated `.needs-review` class kept visually and semantically separate from the severity classes (`.severity-low`, `.severity-medium`, `.severity-high`, `.severity-critical`) — different background pattern, an icon, and (per the spec's text-label requirement) the literal string "Needs human review" always rendered in the markup, never conveyed by color alone.

## Risks / Trade-offs

- **[Risk]** `report_ui`'s views depend on phase 2's `get_platform_evidence_for_clause` and phase 3's `get_contract_report` selector shapes, neither of which exists yet. -> **Mitigation**: both are documented above as explicit forward-reference assumptions (name, args, return shape); when `add-razorpay-crosscheck` and `add-risk-scoring-report` are actually written, reconciling their real selectors against this document is a named, scoped check, and `report_ui`'s own tests are written against the assumed dataclasses so any shape mismatch fails loudly (import error or test failure) rather than silently rendering an empty page.
- **[Risk]** The AST-based guardrail scanner can miss a write call routed through fully dynamic dispatch (e.g., `getattr(client, method_name)(...)` where `method_name` is computed at runtime). -> **Mitigation**: scope the automated guardrail requirement to what static analysis can reliably resolve (spec: Requirement "Production-path source is scanned for write calls" names concrete HTTP verbs and SDK call syntax); the scanned-file-list disclosure (spec: Requirement "Scanned file list is disclosed") lets a human reviewer manually audit anything the automated scan can't statically resolve, and the `verify_guardrail` command's non-zero exit on any straightforward `.post(`/`.put(`/`.patch(`/`.delete(` call still catches the common regression case in CI.
- **[Risk]** Rendering full `llm_response_raw` JSON for every audit entry on one page could make the audit-log page heavy for a contract with many clauses. -> **Mitigation**: each entry's raw response renders inside a collapsed-by-default `<details>` element (server-rendered, no separate AJAX call needed since there's no build step to support one cleanly) so the page loads with only metadata visible per entry.
- **[Risk]** Because `report_ui` has no authentication, anyone with network access to the Django process can view contract reasoning chains and raw model responses. -> **Mitigation**: accepted for buildathon demo scope per Non-Goals; flagged here so it is not mistaken for an oversight if this phase is extended toward production use.

## Migration Plan

Greenfield app, no models: `python manage.py startapp report_ui`, add to `INSTALLED_APPS`, wire `report_ui/urls.py` into `config/urls.py`, verify `manage.py check` passes. No `makemigrations`/`migrate` step is needed since this app defines no models. Rollback is removing the `INSTALLED_APPS` entry and the URL include — no data is affected since every view in this app is read-only over other apps' data and this app owns no database state of its own.
