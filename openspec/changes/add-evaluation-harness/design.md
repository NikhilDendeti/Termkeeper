## Context

See proposal.md - Why for motivation. By the time this change is built, phases 1-3 exist: `contracts.models.Contract`/`Clause`, `pipeline.services.run_pipeline` (stages 1-3), `razorpay_integration.models.MismatchFlag`/`PlatformRecord` and `razorpay_integration.services.RazorpayConnector` (stage 4, phase 2), and a `risk_scoring` app's `RiskAssessment` model (stages 5-6, phase 3). This phase adds no new pipeline stage and changes no existing model — it adds a new `evaluation` app that generates its own input data (synthetic contracts, run through the existing pipeline unmodified) and scores the existing pipeline's persisted output against human labels it also owns.

## Goals / Non-Goals

**Goals:**
- Make precision/recall/calibration/cost claims about the pipeline reproducible and checkable by any contributor running one command, against a split that cannot silently drift.
- Keep every metric that risks hiding a real failure mode reported separately rather than folded into one score: binary F1 vs. calibration, risk-severity vs. mismatch-flag correctness, FP cost vs. FN cost.
- Reuse `pipeline.services.run_pipeline` and `razorpay_integration.services.RazorpayConnector` exactly as phases 1-3 built them — the eval harness is a consumer of those services, not a fork of their logic.

**Non-Goals:**
- No new pipeline stage, no changes to `Contract`, `Clause`, `ExtractedTerm`, `MismatchFlag`, `RiskAssessment`, or `AuditLogEntry` schemas.
- No CI wiring, no scheduled/automatic eval runs, no dashboard — `eval run` is an operator-invoked management command that produces one `EvalRun` row.
- No cross-check against real anonymized customer contracts; the dataset is entirely synthetic.

## Decisions

**New Django app: `evaluation`.**
Owns the models, services, selectors, fixtures, and management command described below. Depends on `contracts`, `pipeline`, `razorpay_integration`, and `risk_scoring` (imports their models/selectors to read pipeline output); none of those apps import from `evaluation`, keeping the dependency direction one-way.

**Models** (`evaluation/models.py`):
- `EvalLabel`: `id: UUID pk`, `contract: FK(Contract)` (the synthetic contract this label belongs to), `clause: FK(Clause, null=True)` (null for contract-level labels such as `overall_risk_tier`), `label_type: enum[risk_severity, mismatch_present]`, `ground_truth_value: JSONField` (holds the rubric fields — `risky`, `severity`, `rationale`, `needs_human_review`, `clause_type` for `risk_severity`; `mismatch_type` and the expected verdict for `mismatch_present`), `annotator: str` (human labeler identifier or `"synthetic-rubric-v1"` for rubric-derived labels applied programmatically at generation time).
- `EvalRun`: `id: UUID pk`, `run_at: DateTimeField(auto_now_add=True)`, `dataset_version: str`, `precision_recall_f1: JSONField` (keyed by `label_type`, e.g. `{"risk_severity": {...}, "mismatch_present": {...}}`), `severity_calibration_score: float`, `false_positive_cost_note: TextField` (holds the FP/FN cost breakdown by `clause_type`/`mismatch_type` and the stated reviewer-minutes assumption, as structured text — the numeric breakdown itself lives alongside `precision_recall_f1` in a second JSONField, `cost_report: JSONField`, added for the same row), `pipeline_version: str` (git short SHA or package version of the code under test), `prompt_version: str` (the prompt version the pipeline stages used for this run, read from `AuditLogEntry` rows produced during the run).

Both models hold fields and simple `clean()`-level validation only (e.g. `EvalLabel.label_type=mismatch_present` requires `clause` non-null) — no cross-model orchestration in the models themselves, per project convention.

**`services.py`** (writes; follows convention, no deviation):
- `generate_synthetic_contract(*, params: SyntheticContractParams) -> Contract` — `SyntheticContractParams` is a typed dataclass carrying the five axis values plus a `seed: int`. Generates ground-truth numeric values first (pure Python, seeded), then calls `core.claude_client.get_structured_completion` to phrase those values into contract prose per `phrasing_style`, then calls `contracts.services.create_contract` to persist it with `engagement_id="synthetic-{dataset_version}-{n}"`. Does not classify or extract — that happens when `run_pipeline` is run against the resulting `Contract` like any other contract.
- `label_synthetic_contract(*, contract: Contract, params: SyntheticContractParams) -> list[EvalLabel]` — writes the per-clause and per-contract `EvalLabel` rows directly from the same ground-truth values used to generate prose (never re-derived from the generated text), applying the `overall_risk_tier` floor rule.
- `run_eval(*, dataset_version: str) -> EvalRun` — orchestrates the full scoring pass: calls `selectors.get_heldout_manifest(dataset_version=dataset_version)`, aborts with `ManifestIntegrityError` (no `EvalRun` row written) if the manifest's recorded hash doesn't match a hash freshly computed over its own listed contract ids, otherwise calls `selectors.score_risk_severity`, `selectors.score_mismatch_flags`, and `selectors.compute_cost_report` (all pure reads) and persists their combined output as one `EvalRun` row.

**`selectors.py`** (reads; follows convention, no deviation):
- `get_heldout_manifest(*, dataset_version: str) -> HeldoutManifest` — reads the committed manifest file (see Manifest hash mechanism below) and returns a typed object exposing `heldout_engagement_ids: list[str]` and `recorded_hash: str`; does not itself raise on mismatch — `run_eval` does the comparison so the abort behavior stays a service-layer (side-effect-relevant) decision.
- `score_risk_severity(*, dataset_version: str) -> RiskSeverityScores` — pure computation over held-out `EvalLabel`/`RiskAssessment` rows; returns precision/recall/F1, `human_review_recall`, and `severity_calibration_score`.
- `score_mismatch_flags(*, dataset_version: str) -> MismatchFlagScores` — pure computation over held-out `EvalLabel(label_type=mismatch_present)`/`MismatchFlag` rows; returns precision/recall.
- `compute_cost_report(*, dataset_version: str, minutes_per_dismissed_flag: float) -> CostReport` — pure computation returning `FP_cost`, `FN_cost`, and their ratio, broken down by `clause_type` and `mismatch_type`.

`score_risk_severity`, `score_mismatch_flags`, and `compute_cost_report` are pure reads with no side effects, so they live in `selectors.py`; only `run_eval`'s final persistence of the `EvalRun` row is a write, so only that step lives in `services.py`. This is the one place this phase's split differs in shape from phase 1's (which had no multi-selector-into-one-write orchestration) — it is still convention: reads in selectors, the one write in services.

**Manifest hash mechanism (concrete):**
- File location: `evaluation/fixtures/<dataset_version>/heldout_manifest.json`, committed to the repository.
- Contents: `{"dataset_version": "v1", "heldout_engagement_ids": ["synthetic-v1-004", "synthetic-v1-017", ...] (sorted ascending), "manifest_sha256": "<hex digest>"}`.
- `manifest_sha256` is computed once, at manifest-authoring time, as `hashlib.sha256("\n".join(sorted(heldout_engagement_ids)).encode("utf-8")).hexdigest()`.
- At `run_eval` time, `get_heldout_manifest` reads the file and recomputes the same hash over the file's own `heldout_engagement_ids` list; `run_eval` compares the recomputed hash to `manifest_sha256`. A mismatch means the id list was hand-edited (or corrupted) after the hash was recorded — for example a contributor added a contract to the held-out set without updating the checksum — and the run aborts before any `EvalRun` row is written.
- Secondarily, `run_eval` also verifies that every `engagement_id` listed actually resolves to a `Contract` row belonging to `dataset_version`; a listed id with no matching `Contract` also aborts the run, catching drift between the manifest and the generated dataset itself.
- Regenerating the dataset for a `dataset_version` regenerates its manifest in the same commit; an existing `dataset_version`'s manifest is never edited in place — a changed split gets a new `dataset_version`.

**Razorpay fixture matrix storage.**
`evaluation/fixtures/razorpay_scenarios/<fixture_version>.json` — a committed list of scenario objects, each holding the contract-clause ground truth, the paired Razorpay test-mode payload (payout history entries or subscription/UPI Autopay config, shaped exactly as `RazorpayConnector`'s test-mode client returns them), and the expected verdict (`mismatch_type` or `no_mismatch` or `unverifiable`). Loading a fixture scenario calls `razorpay_integration.services.RazorpayConnector` configured with Razorpay test-mode credentials (`key_id`/`key_secret` from a `.env`-scoped test-mode credential pair, never the production pair) — the same connector phase 2 built, not a reimplementation.

**Management command.**
`evaluation/management/commands/eval.py` implements a single `eval` command with a `run` subcommand: `python manage.py eval run --dataset eval/v1` parses `--dataset` into a `dataset_version`, calls `evaluation.services.run_eval(dataset_version=...)`, and prints the resulting `EvalRun`'s metrics to stdout.

## Risks / Trade-offs

- **[Risk]** A synthetic dataset, however varied across five axes, may not capture the phrasing diversity of real freelance contracts. -> **Mitigation**: `phrasing_style` includes `legalese` and `deliberately-vague` specifically to stress-test extraction robustness beyond plain prose; revisit with real anonymized contracts only once available (out of scope for this phase — no such corpus exists yet).
- **[Risk]** Generating ground truth first and phrasing it second could still leave the numeric values trivially parseable (e.g. "$500 every 30 days" verbatim), inflating measured precision relative to real contracts that phrase terms more indirectly. -> **Mitigation**: the `deliberately-vague` phrasing style is required to appear in the dataset (axis coverage requirement) and forces indirect phrasing (e.g. "monthly" rather than "every 30 days"); the cost/calibration reports are broken down in a way that lets a reviewer check whether performance drops specifically on vague-phrasing contracts.
- **[Risk]** The manifest-hash refusal check could block a legitimate, intentional dataset change if a contributor forgets to regenerate the manifest. -> **Mitigation**: this is the intended failure mode, not a bug — the fix is always to regenerate the manifest as part of the same change that regenerates the dataset, never to bypass the check; `dataset_version` is bumped whenever the underlying contract set changes, so old versions' manifests never need editing.
- **[Risk]** Test-mode Razorpay fixture payloads could drift from the real API's schema as the `razorpay` SDK or API evolves. -> **Mitigation**: fixtures are versioned (`fixture_version`) and reviewed for schema drift whenever the `razorpay` SDK dependency is upgraded; a mismatch would surface as `RazorpayConnector` parsing errors against production data long before it silently corrupts eval scores, since the connector code path is shared between fixtures and production.
- **[Risk]** Reviewer-minutes-per-dismissed-flag is a stated assumption, not a measured constant, so `FP_cost` in absolute terms is only as good as that assumption. -> **Mitigation**: the assumption is a named parameter (`minutes_per_dismissed_flag`) passed explicitly to `compute_cost_report` and recorded in `false_positive_cost_note`, never hardcoded silently, so a reader can see exactly what produced the number and rerun with a different assumption.

## Migration Plan

New app, no data migration from an existing schema: `manage.py makemigrations evaluation` produces the initial migration for `EvalLabel`/`EvalRun`; `manage.py migrate evaluation` applies it. Rollback in local dev is `manage.py migrate evaluation zero`. Committed fixture/manifest assets are added under `evaluation/fixtures/` in the same change; nothing in the production pipeline path (phases 1-3's `run_pipeline`) is touched, so this phase carries no production migration risk beyond adding two new, empty tables.
