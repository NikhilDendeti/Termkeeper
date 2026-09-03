## Why

Phase 4 of 5 in the build order. It must land after `add-django-foundation` (phase 1, provides `Contract`/`Clause`), `add-razorpay-crosscheck` (phase 2, provides `MismatchFlag`/`PlatformRecord`/`RazorpayConnector`), and `add-risk-scoring-report` (phase 3, provides `RiskAssessment`). Every earlier phase produces flags and asserts they're reasoned about correctly, but nothing measures that assertion against known-correct answers — a confidently wrong `RiskAssessment` and a correctly cautious `needs_human_review` look identical from inside the pipeline itself. This phase builds the held-out evaluation harness that makes precision, recall, and cost claims checkable rather than asserted.

**Non-goals**: this phase does not change any pipeline stage's behavior, add a vendor-facing dashboard (that's phase 5's report viewer), run against a live/production Razorpay account (all cross-check evaluation uses test-mode fixtures per the project's read-only-on-live-data guardrail), or build a continuous CI gate that blocks merges on score regressions — it defines and runs one `eval run` command that produces a persisted, queryable `EvalRun` record, not a dashboard or a CI integration.

## What Changes

- New `evaluation` Django app: `EvalLabel` and `EvalRun` models.
- Synthetic contract dataset generator producing 30-50 contracts crossed over five axes (`engagement_type`, `domain`, `clause_severity_profile` assigned per-clause not uniformly, `phrasing_style`, `razorpay_reference_type`), with concrete numeric ground truth (amount, cadence_days, notice_period_days, penalty_pct) generated before any contract prose, never reverse-derived from generated text.
- Human labeling rubric applied after generation: per-clause (`clause_type`, `risky`, `severity` 1-5, one-sentence asymmetry rationale, `needs_human_review`) and per-contract (`overall_risk_tier` with a floor rule forcing `critical` on 2+ high-severity clauses).
- A contract-level held-out split (never clause-level) whose membership is locked behind a committed manifest file; the eval run command refuses to score when the live-computed split hash doesn't match the manifest's recorded hash.
- A scoring harness computing: precision/recall/F1 for `risk_severity` (binary, `RiskAssessment.severity != low` vs. the label's `risky` bool), a separate `human_review_recall` metric for clauses labeled `needs_human_review`, a `severity_calibration_score` (partial credit, reported separately from the binary F1), a separate precision/recall pair for `MismatchFlag` correctness (matched by clause id + `mismatch_type`), and a false-positive/false-negative cost report broken down by `clause_type` and `mismatch_type`.
- A fixed, versioned matrix of 10+ paired (contract clause, Razorpay test-mode payout-history-or-subscription-config) fixture scenarios covering every `MismatchFlag.mismatch_type`, plus one true-negative control and one deliberately-unverifiable case.
- A management command, `eval run --dataset eval/v1`, wired to `evaluation.services.run_eval`.

## Capabilities

### New Capabilities
- `evaluation/synthetic-dataset`: generating a 30-50 contract synthetic dataset crossed over five axes with numeric ground truth fixed before prose generation, and a human labeling rubric applied per-clause and per-contract.
- `evaluation/scoring-harness`: scoring the pipeline's `RiskAssessment` and `MismatchFlag` output against held-out human labels behind a manifest-hash-enforced split, reporting binary precision/recall/F1, calibration, and cost figures as distinct, unblended metrics.
- `evaluation/razorpay-fixtures`: a fixed, versioned test-mode Razorpay fixture matrix covering every mismatch type plus a true-negative control and an unverifiable-term case, isolated from any live Razorpay resource.

### Modified Capabilities
(none — `openspec/specs/` is still empty; every capability above is declared new. If, once `add-django-foundation`, `add-razorpay-crosscheck`, and `add-risk-scoring-report` are applied and archived, any of their requirement text turns out to need revision to accommodate the eval harness, that revision belongs in a future MODIFIED delta against those specs, not here.)

## Impact

- **New code**: `evaluation/` Django app (models, `services.py`, `selectors.py`, `management/commands/eval.py`); committed dataset/fixture assets under `evaluation/fixtures/` (synthetic contract corpus, human labels, held-out manifest, Razorpay test-mode scenario matrix).
- **New dependencies**: none beyond what phases 1-3 already installed (`anthropic`, `factory_boy`, `pytest-django`); split-hash computation uses the stdlib `hashlib`.
- **Depends on**: `contracts.models.Contract`/`Clause` (phase 1), `pipeline.services.run_pipeline` (phase 1) to produce the pipeline output under evaluation, `razorpay_integration.MismatchFlag`/`PlatformRecord`/`RazorpayConnector` (phase 2) for cross-check fixtures, `risk_scoring` app's `RiskAssessment` (phase 3) as the object being scored.
- **Read-only guardrail**: fixture loading and `RazorpayConnector` calls made during eval issue GET requests only, against Razorpay test-mode credentials — never the live-account credentials used by the production pipeline path.
- **Forward-looking note**: synthetic contracts are persisted as ordinary `Contract` rows (distinguished only by an `engagement_id` naming convention, e.g. `synthetic-<dataset_version>-<n>`) so this phase does not need to modify the phase-1 `Contract` schema. When `add-report-ui` (phase 5) is built, revisit whether the report viewer needs to filter synthetic/eval contracts out of any production-facing list.
