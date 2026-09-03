## Context

See proposal.md - Why. Both `reporting` and `evaluation` are already built and fully tested (part of the 373+ passing baseline). This change adds to each without touching pipeline/scoring/cross-check behavior.

## Goals / Non-Goals

**Goals:**
- Make the clause-type breakdown claim literally true of the user-facing report, reusing the same aggregation shape `evaluation`'s cost report already established (so a reader familiar with one recognizes the other).
- Produce one real, committed, regenerable dataset artifact — not a live-DB-only asset.

**Non-Goals:**
- No new DRF endpoint for the breakdown — it's a field on the existing `GET /contracts/<id>/report/` response.
- No dataset *import* tooling in this change (re-loading a snapshot into a fresh DB) — export only. Import is a natural follow-up if ever needed, not required by anything in scope here.

## Decisions

**`reporting/selectors.py::get_contract_report` gains `severity_breakdown_by_clause_type`.** Computed inline in `get_contract_report` from the same `scored` list already built there (no second query): group by `clause.clause_type`, per group compute `{"count": int, "mean_asymmetry_score": float}`. A small private helper `_compute_clause_type_breakdown(scored: list[RiskAssessment]) -> dict[str, dict[str, Any]]` keeps `get_contract_report` itself readable. `reporting/serializers.py::ContractReportSerializer` gains a matching `severity_breakdown_by_clause_type = serializers.DictField(child=serializers.DictField())`. `frontend/src/api/types.ts`'s `ContractReport` interface gains the same field, optional consumption only (existing pages aren't required to render it in this change — the type must exist and be accurate, rendering it is not in scope here).

**`evaluation/services.py` gains `export_dataset_snapshot(*, dataset_version: str) -> dict[str, Any]`.** Reads every Contract whose `engagement_id` starts with `synthetic-{dataset_version}-` (the naming convention `generate_synthetic_contract` already establishes) via a new `contracts.selectors` query or direct filter, and every `EvalLabel` for each. Returns `{"dataset_version": str, "generated_at_note": str, "contracts": [{"engagement_id": str, "raw_text": str, "clause_severity_profile": ..., "contracts_params": {...}, "labels": [...]}]}` — exact param field names taken from `SyntheticContractParams` as it actually exists in `evaluation/dataset_types.py`, read before writing this function, not guessed.

**New CLI subcommand: `manage.py eval generate-dataset --dataset eval/v1 --count 40 --export evaluation/fixtures/dataset/v1/contracts.json`.** Calls `evaluation.services.generate_dataset(dataset_version=..., count=...)` (already exists) followed by `export_dataset_snapshot` and writes the result to the given path, creating parent directories as needed. Follows the same `--dataset` "eval/<version>" parsing already used by the `eval run` subcommand (`_parse_dataset_version`, reused not duplicated).

**The committed snapshot itself** is produced by actually running this new subcommand once against a clean local DB (not hand-authored JSON), then committing the resulting file — the implementing agent runs the real command and commits its real output.

## Risks / Trade-offs

- **[Risk]** The exported JSON contains full contract text for 30-50 synthetic contracts — a moderately large committed file. → **Mitigation**: synthetic, non-sensitive, generated text; size is bounded by the existing 30-50 contract cap already enforced by `generate_dataset`/`build_dataset_params`.
- **[Risk]** `severity_breakdown_by_clause_type` duplicates aggregation logic conceptually similar to `evaluation.selectors.compute_cost_report`'s `by_clause_type` grouping. → **Mitigation**: accepted — `reporting` must not import from `evaluation` (inverted dependency, `evaluation` depends on `reporting`'s reads, never the reverse), so a small amount of parallel grouping logic in two apps is the correct trade-off, not a refactor target.

## Migration Plan

No model changes, no migrations. Rollout: (1) add the breakdown field + serializer + frontend type, verify no existing report/API/frontend test breaks; (2) add the export function + CLI subcommand, verify with a throwaway dataset_version first; (3) generate and commit the real `v1` snapshot as the last step, once the exporter itself is proven correct.
