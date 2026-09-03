## 1. `risk_scoring` app — model and scaffold

- [x] 1.1 Create the `risk_scoring` app (apps.py, models.py, services.py, selectors.py, migrations/, tests/) and register it in `INSTALLED_APPS`, verify `manage.py check` passes
- [x] 1.2 Add the `RiskAssessment` model per design.md (OneToOneField to Clause, severity choices, bounded asymmetry_score, explanation, nullable suggested_rewrite, linked_mismatch_flag_ids array field, created_at) with a `CheckConstraint` on the asymmetry_score bound, run `manage.py makemigrations risk_scoring`, hand-review the migration, and verify `manage.py migrate` applies it cleanly
- [x] 1.3 Write a model-level test asserting the database rejects an asymmetry_score outside [-1, 1] via the CheckConstraint (spec: Bounded asymmetry score)
- [x] 1.4 Write a model-level test asserting a second RiskAssessment cannot be created for a Clause that already has one without going through an update (spec: Coverage of every classified clause — one assessment per clause)

## 2. `risk_scoring` app — needs_human_review inheritance and mismatch linkage

- [x] 2.1 Implement `risk_scoring/selectors.py::get_linked_mismatch_flags(*, clause) -> QuerySet[MismatchFlag]` filtering `MismatchFlag.objects.filter(extracted_term__clause=clause)`, with a test asserting it returns mismatches from two different ExtractedTerm rows on the same clause and excludes mismatches on other clauses (spec: Mismatch linkage recorded on the assessment)
- [x] 2.2 Implement the needs_human_review short-circuit at the top of `risk_scoring/services.py::score_clause` for `clause.clause_type in (None, "needs_human_review")`, with a test mocking `core.claude_client.get_structured_completion` and asserting it is never called for such a clause, and that the resulting RiskAssessment has severity=needs_human_review (spec: Automatic human review inherited from classification)

## 3. `risk_scoring` app — quote-grounded scoring call

- [x] 3.1 Define the stage-5 structured-output JSON schema (sentences with text/quote pairs, asymmetry_score, suggested_rewrite) and prompt_version constant, with a test that a stubbed conforming response round-trips through the schema unchanged
- [x] 3.2 Implement the quote-grounding validator step in `score_clause` using `core.claude_client.quote_is_verbatim` over every (text, quote) pair, with a test asserting a response where every quote is a verbatim substring of clause_text passes validation (spec: Quote-grounded explanation with anti-hallucination gate — fully grounded explanation persists)
- [x] 3.3 Implement the one-retry-then-forced-needs_human_review fallback for a response containing an unbacked quote, with a test stubbing two consecutive responses that both contain an unbacked quote and asserting the persisted RiskAssessment has severity=needs_human_review and does not contain the unverified explanation text (spec: Quote-grounded explanation with anti-hallucination gate — unbacked sentence forces human review after one retry)
- [x] 3.4 Write a test asserting a response with an unbacked quote on the first attempt but a fully grounded quote on the retry persists the retried explanation and a formula-derived severity, not needs_human_review

## 4. `risk_scoring` app — deterministic severity formula

- [x] 4.1 Implement the `CRITICALITY_WEIGHTS` constant and the base/bump/band formula in `risk_scoring/services.py` exactly as specified in design.md, with a table-driven test covering at least one clause_type at each weight tier (spec: Severity determined by asymmetry, clause-type criticality, and mismatch linkage)
- [x] 4.2 Write a monotonicity test: holding clause_type and mismatch-linkage fixed, increasing abs(asymmetry_score) never decreases the resulting severity band (spec: Severity determined by asymmetry... — higher asymmetry never lowers severity)
- [x] 4.3 Write a mismatch-bump test: holding clause_type and asymmetry_score fixed, a clause with a linked MismatchFlag has a severity band greater than or equal to one without (spec: Severity determined by asymmetry... — confirmed mismatch raises or holds severity)
- [x] 4.4 Write a taxonomy test asserting `RiskAssessment.severity` is always one of the five defined labels across every code path (short-circuit, forced-review, and formula-derived) (spec: Fixed severity taxonomy)

## 5. `risk_scoring` app — coverage, rewrites, and selectors

- [x] 5.1 Wire `score_clause` into `pipeline.services.run_pipeline` as stage 5, called for every Clause on the contract via a function-local import (matching phase 2's precedent for stage 4), with a test asserting a contract with a termination clause and no ExtractedTerm rows still produces exactly one RiskAssessment for it after a full pipeline run (spec: Coverage of every classified clause — non-payment clause scored on text alone)
- [x] 5.2 Implement the suggested_rewrite gate (non-null only for severity in medium/high/critical from a non-forced pass) in `score_clause`, with tests for both the null case (low, needs_human_review) and the populated case (medium/high/critical) (spec: Suggested rewrite scoped to actionable severity)
- [x] 5.3 Implement `risk_scoring/selectors.py::get_risk_assessment_for_clause` and `list_risk_assessments_for_contract`, with a test asserting `get_risk_assessment_for_clause` returns None for an unscored clause and the correct row for a scored one
- [x] 5.4 Verify one `AuditLogEntry` (stage=5) is created per `score_clause` call, including on the needs_human_review short-circuit path, reusing phase 1's audit-logging pattern

## 6. `reporting` app — aggregate selector

- [x] 6.1 Create the `reporting` app (apps.py, selectors.py, serializers.py, views.py, urls.py, management/commands/, tests/) with no models, and register it in `INSTALLED_APPS`, verify `manage.py check` passes
- [x] 6.2 Implement `reporting/selectors.py::get_contract_report` computing overall_risk_score as the mean of the fixed severity weight map (critical=1.0, high=0.75, medium=0.5, low=0.25) over non-needs_human_review RiskAssessments only, with a test asserting one critical + one low RiskAssessment yields overall_risk_score == 0.625 (spec: Fixed severity-to-weight mapping)
- [x] 6.3 Write a test asserting a needs_human_review clause is excluded from the score's numerator and denominator but still appears in needs_human_review_clauses (spec: Human-review clauses excluded from the score — mixed contract)
- [x] 6.4 Write a test asserting a contract where every clause is needs_human_review returns overall_risk_score is None, not 0 (spec: Human-review clauses excluded from the score — all-unreviewed contract)
- [x] 6.5 Populate platform_mismatches from MismatchFlag rows joined through ExtractedTerm/Clause for the contract, with a test asserting every MismatchFlag across two different clauses appears, each identifying its source clause (spec: Mismatches combined into the report)
- [x] 6.6 Write a determinism test calling `get_contract_report` twice against unchanged data (with the Claude client mocked to raise on any call) and asserting identical output both times and zero client invocations (spec: Deterministic, LLM-free aggregation)

## 7. `reporting` app — DRF endpoint

- [x] 7.1 Implement `reporting/serializers.py::ContractReportSerializer` (with nested flagged-clause, mismatch, and needs-human-review serializers) mirroring `get_contract_report`'s dict shape, with a test asserting it round-trips a sample dict without field loss
- [x] 7.2 Implement `reporting/views.py::ContractReportAPIView` (thin `APIView.get`, no business logic) calling `contracts.selectors.get_contract` then `reporting.selectors.get_contract_report`, with a test asserting a GET for a scored contract returns 200 with the expected payload shape (spec: Retrieve-only report endpoint)
- [x] 7.3 Return 404 for an unknown contract_id, with a test asserting a GET for a random UUID returns 404 and no report body (spec: Retrieve-only report endpoint — unknown contract is rejected)
- [x] 7.4 Implement `ContractAuditTrailAPIView` reusing `pipeline.selectors.get_audit_trail`, with a test asserting entries from stages 1 through 5 for a fully-processed contract all appear, ordered oldest first (spec: Audit trail exposed through the same surface)
- [x] 7.5 Wire both views into `reporting/urls.py` and include it from the project URLConf, with a test using `reverse()` to confirm both routes resolve

## 8. `reporting` app — CLI parity

- [x] 8.1 Implement `reporting/management/commands/report_contract.py` with required `--contract-id` and `--format json|md` (default json), delegating to the same `get_contract_report` and audit-trail selectors as the API views, with a test asserting the CLI's JSON output equals the API's JSON body field-for-field for the same contract (spec: Identical content between API and CLI)
- [x] 8.2 Implement the `--format md` rendering as a human-readable representation of the identical data (one section per flagged clause, mismatches, needs-human-review clauses, audit trail), with a test asserting every clause/mismatch/score present in the JSON output also appears in the markdown output (spec: CLI format parity and validation — markdown matches JSON content)
- [x] 8.3 Reject any `--format` value other than json/md with a `CommandError` raised before any output is written, with a test asserting `--format bogus` exits nonzero and produces no report output (spec: CLI format parity and validation — unsupported format rejected cleanly)

## 9. Guardrail verification

- [x] 9.1 Write a test that snapshots row counts for Contract, Clause, ExtractedTerm, PlatformRecord, MismatchFlag, and RiskAssessment, invokes the report endpoint and the report_contract command multiple times against the same contract, and asserts every count is unchanged afterward (spec: Read-only report surface)
- [x] 9.2 Write a static-scan test (matching phase 2's client.py scan pattern) confirming no code path reachable from `reporting.selectors.get_contract_report`, `ContractReportAPIView`, `ContractAuditTrailAPIView`, or `report_contract` calls any `.save()`, `.create()`, `.update()`, `.delete()`, or `bulk_create`/`bulk_update` on a Django model

## 10. Full verification

- [x] 10.1 Run the full test suite (`pytest`) covering `risk_scoring` and `reporting` alongside the existing phase 1/2 suites, all green
- [x] 10.2 Run the project's type-checker (`mypy`) across `risk_scoring/` and `reporting/` with zero errors, confirming every `services.py`/`selectors.py` function signature matches design.md exactly (keyword-only args, typed returns)
- [x] 10.3 Run `openspec validate add-risk-scoring-report --strict` and fix any reported issues until it passes
