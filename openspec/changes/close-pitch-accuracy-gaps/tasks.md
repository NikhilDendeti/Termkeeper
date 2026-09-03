## 1. Reporting — clause-type breakdown

- [x] 1.1 Implement `_compute_clause_type_breakdown` and wire it into `reporting/selectors.py::get_contract_report` as `severity_breakdown_by_clause_type`, with a test asserting counts/mean-asymmetry per clause_type for a contract with multiple scored clause types (spec: Report includes a per-clause-type severity breakdown)
- [x] 1.2 Write a test asserting an empty breakdown (not omitted, not an error) for a contract with no scored clauses yet (spec: No scored clauses yields an empty breakdown)
- [x] 1.3 Write a test asserting a needs_human_review clause never contributes to any group (spec: Breakdown excludes needs-human-review clauses)
- [x] 1.4 Add `severity_breakdown_by_clause_type` to `reporting/serializers.py::ContractReportSerializer`, verify the existing `ContractReportAPIView` test(s) still pass and add one asserting the new field appears in the live response
- [x] 1.5 Add the matching field to `frontend/src/api/types.ts`'s report type and verify `npm run build` in `frontend/` still succeeds with zero TypeScript errors
- [x] 1.6 Run the full backend suite (`pytest -q`) and confirm every previously-passing test still passes

## 2. Evaluation — dataset snapshot export

- [x] 2.1 Read `evaluation/dataset_types.py`'s `SyntheticContractParams` as it actually exists, then implement `evaluation/services.py::export_dataset_snapshot(*, dataset_version)`, with a test asserting the export contains exactly N entries for an N-contract generated dataset, each with its raw_text and labels
- [x] 2.2 Add the `eval generate-dataset` subcommand to `evaluation/management/commands/eval.py`, reusing the existing `_parse_dataset_version` helper, with a test exercising it against a throwaway dataset_version and asserting the export file is written with the expected shape
- [ ] 2.3 **BLOCKED** — run `manage.py eval generate-dataset --dataset eval/v1 --count 40 --export evaluation/fixtures/dataset/v1/contracts.json` for real against a local DB, verify the output file's contract count is in [30,50] and every engagement_id matches `synthetic-v1-<n>`, and commit the resulting file. Requires a real `ANTHROPIC_API_KEY` in `.env` (currently empty) — the generator calls the live Claude API to phrase each synthetic contract's clauses, and the implementing agent correctly declined to fabricate this data or stub the LLM call to force a fake "real" run. Code path is proven correct by `evaluation/tests/test_eval_command.py::TestEvalGenerateDatasetCommand` (mocked, per convention). Re-run once a key is set — no further code changes needed.
- [x] 2.4 Run the full backend suite (`pytest -q`) and confirm every previously-passing test still passes

## 3. Verification

- [ ] 3.1 Run `mypy` across `reporting` and `evaluation` and verify zero errors — done informally per-agent (both clean); not yet re-run as one combined final pass
- [ ] 3.2 Run `openspec validate close-pitch-accuracy-gaps --strict` and verify it passes — deferred until 2.3 is unblocked, since the change isn't fully applied yet
