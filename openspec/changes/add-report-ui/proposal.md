## Why

The pipeline, cross-check, and risk-scoring phases produce clause-level reasoning chains, an audit trail, and a no-write-calls guardrail, but none of it is browsable — a reviewer would have to query the database or trust a claim in documentation. This is phase 5 of 5 in the build order; it must land after `add-risk-scoring-report` (phase 3), whose aggregate report selector this phase's clause-report page renders, and it depends on `add-razorpay-crosscheck` (phase 2) for the `razorpay_integration` source files its guardrail-verification page scans and for the platform-evidence data its reasoning-chain view displays.

**Non-goals**: this phase adds no models, no DRF endpoints, and no business logic beyond assembling selector output into template context — it is a read-only rendering layer over data phase 1 through 3 already compute and persist. It does not change how clauses are scored, how mismatches are detected, or how the audit trail is written; it only makes those things visible. It does not add authentication/authorization to the report views (single-tenant demo scope for the buildathon) and does not add a Node-based frontend, per the project's server-rendered-templates decision.

## What Changes

- New `report_ui` Django app (no models) with three views: `contract_report_view` (clause-by-clause reasoning chain), `contract_audit_log_view` (full `AuditLogEntry` trail for a contract), and `guardrail_verification_view` (proof that `razorpay_integration`'s production path issues no write calls).
- A `report_ui/selectors.py::scan_razorpay_guardrail` function that statically scans `razorpay_integration`'s production-path source files (excluding the test-mode fixture/demo-seeding module phase 2 isolates) for HTTP write calls and SDK write operations, returning a pass/fail result plus the scanned file list and any violations.
- A `verify_guardrail` management command wrapping the same scan for CI/local use, exiting non-zero on any violation.
- Django templates (`report_ui/templates/report_ui/`: `base.html`, `contract_report.html`, `contract_audit_log.html`, `guardrail_verification.html`) rendering the three views, with a dedicated CSS treatment that renders any `needs_human_review` item distinctly from every scored severity level — text label plus styling, never color alone.
- Plain CSS under `report_ui/static/report_ui/css/report.css`, no build step, no new frontend dependency.
- New URL routes under the project's `config/urls.py` for the three views.

## Capabilities

### New Capabilities
- `report-ui/reasoning-chain-view`: a server-rendered page listing a contract's clauses, each expandable to its full reasoning chain (clause text, classification, extracted term, platform evidence, risk verdict), with `needs_human_review` items rendered in a visual treatment never shared with a scored severity.
- `report-ui/audit-log-view`: a server-rendered page listing a contract's complete `AuditLogEntry` trail in stage order, with each entry's `prompt_version`, `model_name`, `latency_ms`, and inspectable raw `llm_response_raw`.
- `report-ui/guardrail-verification-view`: a server-rendered page proving, via a live static scan (not an assertion), that `razorpay_integration`'s production path issues no write calls against live data, disclosing the scanned file list and any violations found.

### Modified Capabilities
(none — `openspec/specs/` has no archived capability yet for `report_ui`, `pipeline`, or `razorpay_integration` at the time this proposal is written, so there is nothing to point a Modified delta at. This phase does not change the externally observable behavior of any phase 1-3 requirement — it only renders data those phases already persist — so no forward-looking revisit note is needed here either.)

## Impact

- **New code**: `report_ui/` Django app — `views.py`, `selectors.py`, `urls.py`, `templates/report_ui/`, `static/report_ui/css/`, `templatetags/report_ui_extras.py` (a `pretty_json` filter for the audit-log view), `management/commands/verify_guardrail.py`.
- **New dependencies**: none — uses Django's own template engine, static file handling, and `ast` (standard library) for the guardrail scan. No new package is added to `pyproject.toml`.
- **Reads (no writes)**: `contracts.selectors.get_contract`, `contracts.selectors.list_clauses_for_contract`, `pipeline.selectors.get_audit_trail`, `pipeline.selectors.list_extracted_terms_for_clause` (phase 1); the phase 2 `razorpay_integration` platform-evidence selector and phase 3 `risk_scoring` reporting selector this phase's views call are named as forward-reference assumptions in design.md, since phases 2 and 3 have not been written yet in this project's sequencing.
- **Infrastructure**: none new — served by the same Django process as the rest of the project; static CSS collected via Django's existing `collectstatic` in production settings already scaffolded by phase 1.
