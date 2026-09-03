## 1. App scaffold and routing

- [x] 1.1 Create the `report_ui` app (no models), register it in `INSTALLED_APPS`, and verify `manage.py check` passes with zero models registered for this app
- [x] 1.2 Add `report_ui/urls.py` with the three routes (`contract_report`, `contract_audit_log`, `guardrail_verification`) and include it from `config/urls.py`, and verify `manage.py show_urls` (or `resolve()` in a test) lists all three names
- [x] 1.3 Add `report_ui/templates/report_ui/base.html` (shared layout, nav links between the three pages) and verify it renders with no context via a minimal smoke test

## 2. Reasoning-chain view (spec: `report-ui/reasoning-chain-view`)

- [x] 2.1 Implement `report_ui/views.py::contract_report_view` calling `contracts.selectors.get_contract` and `risk_scoring.selectors.get_contract_report`, and verify it returns HTTP 200 for a contract with at least one clause
- [x] 2.2 Implement `contract_report.html` listing clauses in `sequence_index` order, and write a test asserting clause order in the rendered HTML matches `sequence_index` ascending (spec: Clauses listed in sequence order)
- [x] 2.3 Implement the expandable per-clause section rendering clause text, classification, extracted term with verbatim span, platform evidence, and risk verdict in that order, with a test asserting all five elements appear for a fully processed clause (spec: Full reasoning chain shown per clause)
- [x] 2.4 Write a test asserting a clause with no platform evidence renders the literal "no platform evidence available" message rather than an empty section (spec: Clause with no platform evidence)
- [x] 2.5 Write a test asserting a clause with an extracted term but no risk verdict renders the literal "not yet assessed" message (spec: Clause not yet risk-scored)
- [x] 2.6 Add the `.needs-review` CSS class (visually distinct from `.severity-low/medium/high/critical`, no shared color) to `report.css`, and write a test asserting a `needs_human_review = true` item's rendered HTML never carries any `.severity-*` class (spec: needs_human_review renders distinctly from every scored severity)
- [x] 2.7 Write a test asserting the needs-human-review label text is present in the rendered page even when CSS is stripped from consideration, i.e. checking `response.content` text, not just class names (spec: needs-human-review state conveyed by text label, not color alone)
- [x] 2.8 Write a test asserting a clause flagged `needs_human_review` at classification still renders that treatment independent of its later risk verdict severity (spec: Distinct treatment holds independent of later stages)

## 3. Audit-log view (spec: `report-ui/audit-log-view`)

- [x] 3.1 Implement `report_ui/views.py::contract_audit_log_view` calling `contracts.selectors.get_contract` and `pipeline.selectors.get_audit_trail`, and verify it returns HTTP 200 for a contract with audit entries
- [x] 3.2 Implement `contract_audit_log.html` listing entries ordered by stage then `created_at`, with a test asserting rendered order matches that ordering for a contract with entries across 3+ stages (spec: Complete audit trail rendered in stage order)
- [x] 3.3 Render `prompt_version`, `model_name`, and `latency_ms` inline per entry, with a test asserting all three values appear in the rendered HTML for each entry (spec: Entry metadata visible without further navigation)
- [x] 3.4 Implement the `pretty_json` template filter in `report_ui/templatetags/report_ui_extras.py` and a collapsed `<details>` block per entry showing the formatted `llm_response_raw`, with a test asserting the full raw response content is present in `response.content` (spec: Raw model response inspectable per entry)
- [x] 3.5 Write tests asserting a clause-scoped entry displays its clause identity and a null-clause entry (e.g. stage 1) renders with no clause association (spec: Clause-scoped entries are distinguishable from contract-level entries)

## 4. Guardrail verification (spec: `report-ui/guardrail-verification-view`)

- [x] 4.1 Implement `report_ui/selectors.py::scan_razorpay_guardrail` using `ast.parse`/`ast.walk` over `razorpay_integration/client.py` and `razorpay_integration/services.py`, excluding `razorpay_integration/testmode_fixtures.py`, and write a unit test with a fixture file containing a `.post(` call asserting it is captured as a violation with correct file/line/call
- [x] 4.2 Write a unit test with a fixture file containing only read (`.get(`) calls asserting `passed=True` and zero violations (spec: Clean scan renders a pass)
- [x] 4.3 Write a unit test asserting the excluded fixture/demo-seeding module is never included in `scanned_files` even if it contains write calls (spec: Scan covers production files and excludes fixtures)
- [x] 4.4 Implement `report_ui/views.py::guardrail_verification_view` and `guardrail_verification.html` rendering the scanned file list and the pass/fail result, with a test asserting every path in `scanned_files` appears in the rendered HTML (spec: Scanned file list is disclosed)
- [x] 4.5 Write a test asserting a fail result lists file, line, and matched call for every violation, rendered in the page (spec: A violation renders a fail with evidence)
- [x] 4.6 Write a test that scans, removes/fixes a violation from a temp copy of a fixture, re-scans, and asserts the violation no longer appears — proving the scan is live, not cached (spec: A fixed violation no longer appears on the next scan)
- [x] 4.7 Implement `report_ui/management/commands/verify_guardrail.py` and verify it exits 0 on a clean scan and 1 on a scan with at least one violation

## 5. Styling and cross-page navigation

- [x] 5.1 Finalize `report_ui/static/report_ui/css/report.css` covering layout, severity classes, and the `.needs-review` treatment, and verify `manage.py collectstatic --dry-run` picks it up with no errors
- [x] 5.2 Add cross-links between `contract_report.html`, `contract_audit_log.html`, and `guardrail_verification.html`, and verify each link resolves via a smoke test following each link from a rendered page

## 6. Verification

- [x] 6.1 Run the full test suite for `report_ui` (and re-run `core`/`contracts`/`pipeline` to confirm no regression) and verify all tests pass
- [x] 6.2 Run `mypy` across `report_ui` and verify no type errors, including the `GuardrailScanResult`/`GuardrailViolation` dataclasses and the assumed phase 2/3 selector return types
- [x] 6.3 Run `openspec validate add-report-ui --strict` and verify it passes before requesting archive
