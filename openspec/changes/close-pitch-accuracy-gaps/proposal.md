## Why

A pitch-accuracy review (verified independently against the real code — see PITCH.md and the verification evidence) found two claims that were false as stated but cheap to make true: the user-facing report doesn't break risk down by clause type (only the internal eval cost report does), and the 30-50 contract synthetic dataset is fully regenerable but never actually committed to the repo. Both are small, additive, low-risk closes rather than pitch corrections. This is not part of the five-phase build order — it's a standalone accuracy-closing change against already-shipped, already-tested apps.

**Non-goals**: this does not touch pipeline, risk-scoring, or Razorpay cross-check behavior — only reporting's read composition and evaluation's dataset tooling. It does not add the third open item (a live Razorpay sandbox demo run) — that needs real test-mode credentials this environment doesn't have.

## What Changes

- `reporting/selectors.py::get_contract_report` gains a `severity_breakdown_by_clause_type` field (counts and mean asymmetry per clause_type, mirroring the aggregation `evaluation`'s cost report already does), exposed through the existing report DRF endpoint, CLI command, and frontend types — no new endpoint needed.
- `evaluation` gains a dataset-snapshot export: a service function serializing a generated dataset (every Contract's raw_text, engagement_id, dataset params, and every EvalLabel) to portable JSON, a new `eval generate-dataset` management subcommand that generates, labels, and exports in one step, and an actual committed snapshot file for `dataset_version=v1`.

## Capabilities

### New Capabilities
- `reporting/clause-type-breakdown`: the aggregate report groups flagged-clause severity by clause type, in addition to the existing single overall score.
- `evaluation/dataset-snapshot-export`: a generated synthetic dataset can be exported to a portable, committable JSON snapshot and the resulting file is checked into the repo.

### Modified Capabilities
(none declared — no prior change has been archived, so there is nothing under `openspec/specs/` to declare a delta against; same constraint as every prior change in this project.)

## Impact

- **Changed code**: `reporting/selectors.py`, `reporting/serializers.py`, `frontend/src/api/types.ts` (new field only, backward compatible); `evaluation/services.py`, `evaluation/management/commands/eval.py`.
- **New committed artifact**: `evaluation/fixtures/dataset/v1/contracts.json` (or equivalent path chosen in design.md).
- **No impact** on any pipeline, scoring, or cross-check behavior, and no impact on any already-passing test's assertions (only new fields/files are added).
