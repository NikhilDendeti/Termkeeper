## 1. `evaluation` app scaffold

- [x] 1.1 Create the `evaluation` app, register it in `INSTALLED_APPS`, and verify `manage.py check` passes
- [x] 1.2 Add the `EvalLabel` and `EvalRun` models per design.md, run `makemigrations evaluation`, hand-review the generated migration, and verify `manage.py migrate` applies it cleanly
- [x] 1.3 Add a `SyntheticContractParams` typed dataclass (five axis fields + `seed: int`) and unit-test that constructing it rejects an out-of-taxonomy axis value

## 2. Synthetic dataset generation (spec: `evaluation/synthetic-dataset`)

- [x] 2.1 Implement ground-truth-first generation (amount, cadence_days, notice_period_days, penalty_pct) as a pure seeded function, with a unit test asserting two calls with the same seed produce identical ground truth (spec: Ground truth generated before prose)
- [x] 2.2 Implement `evaluation/services.py::generate_synthetic_contract`, calling `core.claude_client.get_structured_completion` to phrase pre-generated ground truth into prose per `phrasing_style`, then `contracts.services.create_contract`; write a test asserting the persisted `Contract`'s ground truth values are never parsed from its own `raw_text` (spec: Ground truth generated before prose)
- [x] 2.3 Implement per-clause severity assignment allowing a fair-profile contract to contain an exploitative clause, with a test asserting this mix occurs in at least one generated contract per dataset (spec: Severity varies within one contract)
- [x] 2.4 Generate the full `eval/v1` dataset (30-50 contracts) and write a test asserting every value of all five axes appears at least once (spec: Full axis coverage across the dataset) and the contract count is between 30 and 50 (spec: Dataset size within bounds)
- [x] 2.5 Implement `evaluation/services.py::label_synthetic_contract` writing the per-clause rubric (`clause_type`, `risky`, `severity`, `rationale`, `needs_human_review`) as `EvalLabel(label_type=risk_severity)` rows, with a test asserting all five fields are present and `rationale` is non-empty for every generated clause (spec: Label completeness)
- [x] 2.6 Implement the per-contract `overall_risk_tier` floor rule, with a test asserting a contract with two severity-4 clauses and no severity-5 clause is still labeled `critical` (spec: Floor rule forces critical tier)

## 3. Held-out manifest (spec: `evaluation/scoring-harness`)

- [x] 3.1 Implement the contract-level held-out split assignment at dataset-generation time, with a test asserting no contract's clauses are split across the held-out and non-held-out sets (spec: No clause-level leakage)
- [x] 3.2 Author the committed `evaluation/fixtures/eval/v1/heldout_manifest.json` (sorted `heldout_engagement_ids` + `manifest_sha256`) and implement `evaluation/selectors.py::get_heldout_manifest`, with a test asserting it correctly recomputes the hash over the file's own id list
- [x] 3.3 Wire the manifest-hash comparison into `evaluation/services.py::run_eval`, with a test asserting a hand-edited id list (hash now mismatched) causes the run to abort with no `EvalRun` row persisted (spec: Mismatched manifest blocks the run)
- [x] 3.4 Write a test asserting a matching manifest lets `run_eval` proceed to scoring and persist an `EvalRun` row (spec: Matching manifest proceeds)

## 4. Razorpay test-mode fixture matrix (spec: `evaluation/razorpay-fixtures`)

- [x] 4.1 Author `evaluation/fixtures/razorpay_scenarios/v1.json` with at least 10 paired (clause, Razorpay test-mode payload) scenarios, one per `MismatchFlag.mismatch_type`, and write a test asserting every `mismatch_type` value is covered (spec: Every mismatch type is covered, Minimum matrix size)
- [x] 4.2 Add the true-negative control scenario (fair clause, matching test-mode data) and a test asserting stage 4 raises no `MismatchFlag` for it (spec: Control produces no flag)
- [x] 4.3 Add the deliberately-unverifiable scenario (term with no corresponding Razorpay field) and a test asserting stage 4 records it as unverifiable rather than producing a fabricated `MismatchFlag` (spec: Unverifiable term declines rather than fabricates)
- [x] 4.4 Record `fixture_version` on every `EvalRun` that scores against the matrix, with a test asserting the version is present on the persisted row (spec: EvalRun records the fixture version used)
- [x] 4.5 Configure fixture loading to use Razorpay test-mode credentials exclusively, with a test (mocking the live-credential path) asserting no call targets a non-test-mode resource (spec: No live-resource calls during fixture evaluation)

## 5. Scoring harness — risk severity metrics (spec: `evaluation/scoring-harness`)

- [x] 5.1 Implement `evaluation/selectors.py::score_risk_severity`'s binary precision/recall/F1 over held-out, non-`needs_human_review` clauses, with a test asserting the TP/FP/FN classification matches a hand-computed example (spec: Binary comparison drives the metric)
- [x] 5.2 Implement the `needs_human_review` exclusion and separate `human_review_recall` computation, with a test asserting a `needs_human_review`-labeled clause never contributes to the binary F1 (spec: Ambiguous clauses excluded from the binary metric)
- [x] 5.3 Implement `severity_calibration_score` (1.0 exact, 0.5 off-by-one, 0.0 otherwise) as a field distinct from `risk_severity` F1, with a test asserting an off-by-one prediction scores exactly 0.5 and that no code path folds it into the F1 value (spec: Partial credit for off-by-one severity, Calibration never blended into F1)

## 6. Scoring harness — mismatch flag and cost metrics (spec: `evaluation/scoring-harness`)

- [x] 6.1 Implement `evaluation/selectors.py::score_mismatch_flags` matching on clause id and `mismatch_type` together, with a test asserting a flag with the right clause id but wrong `mismatch_type` does not count as a true positive (spec: Match requires both clause id and mismatch_type)
- [x] 6.2 Implement `evaluation/selectors.py::compute_cost_report` (`FP_cost`, `FN_cost`, their ratio, broken down by `clause_type` and `mismatch_type`), with a test asserting the breakdown is present and no single blended cost number is returned in its place (spec: Costs broken down, never blended)

## 7. Eval run orchestration and CLI

- [x] 7.1 Implement `evaluation/services.py::run_eval` composing the manifest check and the three selector scoring calls into one persisted `EvalRun` row, with an integration test running it end to end against the `eval/v1` dataset and asserting all `EvalRun` fields are populated
- [x] 7.2 Implement the `eval run --dataset eval/v1` management command and verify it prints the `EvalRun`'s metrics and exits 0 on a matching manifest, and exits non-zero with no `EvalRun` row on a mismatched one

## 8. Verification

- [x] 8.1 Run the full test suite for the `evaluation` app and verify all tests pass
- [x] 8.2 Run `mypy` across `evaluation` and verify no type errors
- [x] 8.3 Run `openspec validate add-evaluation-harness --strict` and verify it passes before requesting archive
