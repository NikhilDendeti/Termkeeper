## Why

The Payment Terms & Vendor Risk Analyzer has no codebase yet. Every later phase — the Razorpay cross-check, risk scoring, evaluation harness, and report UI — depends on a Django project that already has a working three-stage AI pipeline (segment a contract into clauses, classify each clause, extract its payment terms) persisted through a real schema. This is phase 1 of 5 in the build order; it must land first because `add-razorpay-crosscheck` (phase 2) writes its cross-check output against the `Clause` and `ExtractedTerm` rows this phase creates.

**Non-goals**: this phase does not touch Razorpay in any way (no `razorpay_integration` app, no live-rail cross-check — that's phase 2), does not score risk or produce a report (phase 3), and does not build the evaluation harness (phase 4) or any UI beyond a CLI (phase 5). A `Clause` can be classified and have terms extracted, but nothing yet judges whether those terms are risky.

## What Changes

- New Django project (`config/` settings package, split into `base.py`/`local.py`/`production.py`) using Django's built-in SQLite backend (`db.sqlite3`) — no external database service required for development, testing, or the buildathon demo.
- New `contracts` app: `Contract` and `Clause` models, ingestion service, contract-level selectors.
- New `pipeline` app: `ExtractedTerm` model, `AuditLogEntry` model, and the three pipeline-stage services (`segment_contract`, `classify_clause`, `extract_terms`) plus a Claude API client wrapper enforcing tool-use/JSON-schema output on every call.
- New `core` app (or `libs/` package — decided in design.md): the shared Anthropic client wrapper and the quote-grounding validator (`text.find(quote) != -1`) reused by later phases.
- Two Django management commands: `ingest_contract` (creates a `Contract` + runs stage 1) and `run_pipeline` (runs stages 1–3, or resumes `--from-stage`).
- Project tooling: `pyproject.toml` (ruff + mypy config), `pytest.ini`/`pytest-django` config, `.env.example`. No `docker-compose.yml` — SQLite needs no external service.

## Capabilities

### New Capabilities
- `contracts/ingestion`: accepting a contract's raw text plus its engagement metadata and persisting it as a `Contract`, ready for the pipeline to run against.
- `pipeline/clause-segmentation`: splitting a contract's raw text into verbatim, position-tracked `Clause` rows via a forced-schema Claude call, with deterministic substring validation and a `needs_human_review` fallback on validation failure.
- `pipeline/clause-classification`: assigning each `Clause` one of the fixed 8-label `clause_type` taxonomy via a forced-schema Claude call, with a confidence-margin gate that forces `needs_human_review` on low or ambiguous confidence.
- `pipeline/term-extraction`: extracting structured `ExtractedTerm` rows (payout frequency, milestone trigger, penalty amount, notice period, auto-renewal terms) from `payment_schedule`/`penalty_late_fee`/`auto_renewal` clauses via a forced-schema Claude call, never inferring a value not stated in the clause text.
- `pipeline/audit-trail`: recording one `AuditLogEntry` per pipeline stage invocation (prompt version, raw model response, latency, resulting rows), queryable per contract.

### Modified Capabilities
(none — this is the first change in the project; there is no existing `openspec/specs/` yet)

## Impact

- **New code**: `config/`, `contracts/`, `pipeline/`, `core/` Django apps; two management commands; Alembic is not used — Django migrations only, created via `manage.py makemigrations` and reviewed by hand per project convention.
- **New dependencies**: `django`, `djangorestframework` (installed now even though phase 1 exposes no endpoints yet, so phase 2–3 don't need a separate dependency-add change), `anthropic`, `pytest`, `pytest-django`, `factory_boy`, `ruff`, `mypy`. No database driver needed — SQLite support is built into Python/Django.
- **Infrastructure**: local SQLite file (`db.sqlite3`, gitignored); `ANTHROPIC_API_KEY` required in `.env`.
- **No impact yet** on Razorpay, risk scoring, evaluation, or UI — those are later changes and must read `Clause`/`ExtractedTerm` as this phase defines them without modification wherever possible.
