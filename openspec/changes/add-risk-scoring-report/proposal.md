## Why

The pipeline can currently say what a contract claims (phase 1, stages 1-3) and where those claims diverge from real Razorpay activity (phase 2, stage 4), but nothing yet judges how much any of that actually matters, and nothing surfaces it as a single callable report. This is phase 3 of 5 in the build order; it must land after add-django-foundation (phase 1, for Clause and ExtractedTerm) and add-razorpay-crosscheck (phase 2, for MismatchFlag), since scoring reads both and the report aggregates both.

## What Changes

- Add a new `risk_scoring` Django app, depending on `contracts` (reads Clause) and `razorpay_integration` (reads MismatchFlag via its ExtractedTerm link), with a `RiskAssessment` model and pipeline stage 5.
- Implement `score_clause`, which scores *every* classified Clause — not only clauses with ExtractedTerm rows — producing a severity band, a signed asymmetry_score, a quote-grounded explanation, and an optional suggested rewrite.
- Enforce an anti-hallucination gate on every explanation: each sentence must be backed by a verbatim quote from the clause's own text, checked via `core.claude_client.quote_is_verbatim`; a failing explanation is retried once, and a second failure forces `severity=needs_human_review` instead of persisting unverified text.
- Short-circuit scoring (no LLM call) for any Clause whose `clause_type` is already `needs_human_review` or unset from phase 1 classification, inheriting that state directly into the RiskAssessment.
- Compute severity deterministically from a fixed per-clause-type criticality weight, the magnitude of asymmetry_score, and whether a MismatchFlag is linked through the clause's extracted terms.
- Add a new `reporting` Django app (no new models) with a pure, LLM-free aggregation (`get_contract_report`) combining every contract's RiskAssessment and MismatchFlag rows into an `overall_risk_score`, a ranked flagged-clause list, a platform-mismatch list, and a separate `needs_human_review_clauses` list excluded from the score.
- Extend `pipeline.services.run_pipeline` to invoke stage 5 (`risk_scoring.services.score_clause` per clause) after stage 4, following the same function-local-import pattern phase 2 used to avoid a circular import.
- Expose the aggregate report and full audit trail via a thin DRF retrieve endpoint and a `report_contract --contract-id --format json|md` management command, with identical content between the two surfaces.

## Capabilities

### New Capabilities

- `risk-scoring/clause-severity`: Scores every classified Clause for severity and directional asymmetry from a deterministic formula over asymmetry magnitude, clause-type criticality, and linked platform mismatches, with every explanation sentence verified against a verbatim quote from the clause text before it can be persisted.
- `reporting/aggregate-report`: Combines a contract's already-persisted RiskAssessment and MismatchFlag rows into a deterministic overall_risk_score and supporting lists, with no LLM call and with needs_human_review clauses reported separately so they never silently move the headline number.
- `reporting/report-api`: Exposes a contract's full report and audit trail as a retrieve-only DRF endpoint and an equivalent `report_contract` management command, with identical content across both surfaces and no write side effects.

### Modified Capabilities

(none — see the sequencing note below)

## Impact

- New Django app `risk_scoring`: models.py (RiskAssessment), services.py, selectors.py, apps.py, migrations/, tests/.
- New Django app `reporting`: no models; selectors.py, serializers.py, views.py, urls.py, management/commands/report_contract.py, apps.py, tests/.
- New migration adding the RiskAssessment table, with a foreign key into `contracts.Clause`; `reporting` has no migrations of its own.
- `pipeline.services.run_pipeline` gains a stage-5 call into `risk_scoring.services.score_clause` after stage 4 (see design.md for the import-direction handling).
- Project `urls.py` gains the reporting app's routes.
- Forward-looking note: when add-django-foundation is applied and archived, no phase-1 requirement text needs a MODIFIED delta for this phase — `AuditLogEntry.stage` is already an unconstrained int, so stage=5 (and stage=6, if the report generation step is later audit-logged) is additive by construction, and `Clause.clause_type`'s existing `needs_human_review` value already carries the meaning this phase inherits from. If a future phase finds run_pipeline's own requirement text too narrowly scoped to stages 1-3 to cover stage 5 by example, revisit pipeline's orchestration requirement then.

**Non-goals**: this phase does not build the synthetic evaluation dataset, EvalLabel/EvalRun models, or held-out precision/recall/false-positive-cost scoring (phase 4, add-evaluation-harness); does not build the Django-templates report viewer, clause-expand UI, or guardrail-verification view (phase 5, add-report-ui); does not add scoring history or versioning (re-scoring a clause overwrites its current RiskAssessment; the full reasoning trail for every past attempt still lives in AuditLogEntry from phase 1); and does not make the per-clause-type criticality weights admin-configurable.
