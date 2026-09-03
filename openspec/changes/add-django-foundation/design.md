## Context

See proposal.md - Why. This is the first change in the project: no Django project, no apps, no models exist yet. Everything here is greenfield, so this design also fixes the project-wide conventions (app boundaries, service/selector pattern, migration review) that every later phase (`add-razorpay-crosscheck`, `add-risk-scoring-report`, `add-evaluation-harness`, `add-report-ui`) must follow without re-litigating them.

## Goals / Non-Goals

**Goals:**
- Stand up a Django project where `contracts` and `pipeline` are separate apps with a clean dependency direction: `pipeline` depends on `contracts` (imports its models/selectors), never the reverse.
- Make every pipeline stage a plain, typed, independently callable service function — no stage depends on another stage's Python return value, only on rows the prior stage already wrote to the database. This is what makes `run_pipeline --from-stage N` and per-clause human-review resubmission possible starting from phase 3 onward.
- Force every Claude call through a single shared client wrapper so structured-output enforcement and prompt-version tracking exist in one place, not duplicated per stage.

**Non-Goals:**
- No DRF endpoints are exposed yet (the dependency is installed so phase 3 doesn't need a fresh `pip install` change, but `contracts`/`pipeline` have no `views.py`/`urls.py` in this phase — CLI only).
- No Razorpay code of any kind — not even a stub client. `pipeline` stage 4 does not exist until `add-razorpay-crosscheck`.
- No risk scoring, no report generation.

## Decisions

**App boundaries: `contracts` vs `pipeline` as two apps, not one.**
`contracts` owns `Contract` and `Clause` — the entities that exist independent of any AI processing. `pipeline` owns `ExtractedTerm` and `AuditLogEntry` — the entities that only exist because AI processing ran. Alternative considered: one `contracts` app holding everything. Rejected because phase 2 needs to add a `razorpay_integration` app that depends on `pipeline` (for `ExtractedTerm`) but should not need to depend on contract-ingestion concerns — keeping `pipeline` as its own app now avoids a later app-boundary migration.

**Shared Claude client lives in `core/claude_client.py`, not inside `pipeline`.**
`core` is a small app with no models — just the Anthropic client wrapper (`get_structured_completion(system_prompt: str, user_content: str, schema: dict, *, prompt_version: str) -> dict`) and the quote-grounding validator (`quote_is_verbatim(source: str, quote: str) -> bool`) reused by classification, extraction, and (from phase 3 onward) risk scoring. Alternative considered: put the client directly in `pipeline/services.py`. Rejected because `add-risk-scoring-report` (phase 3) reuses the same grounding validator and putting it in `pipeline` would make `risk_scoring` depend on an app conceptually about segmentation/classification/extraction.

**Follows the HackSoft-style service/selector convention; no deviation.** Every write is a `services.py` function; every non-trivial read is a `selectors.py` function; models carry only fields, `Meta`, and `clean()`-level validation.

**Database: SQLite (Django's built-in backend), not PostgreSQL.** `db.sqlite3` as a single local file, no external service, no Docker, no connection configuration for the buildathon demo or local dev. Every `JSONField` used in this design (`ExtractedTerm.value_structured`, `AuditLogEntry.llm_response_raw`, later `PlatformRecord.payload`) runs on Django's SQLite JSON1-backed `JSONField`, which supports the same query API used here (no querying inside the JSON blobs in phase 1 — it's stored and read back whole). Alternative considered: PostgreSQL via Docker. Rejected for this project: the buildathon demo needs to run on a judge's or teammate's machine with zero infrastructure setup, and nothing in phases 1–5 needs a Postgres-only feature (no full-text search, no concurrent-write tuning, no `ArrayField`). If a future phase needs true concurrent writers or JSON-path querying at scale, revisit then — not a cost worth paying now.

**New Django app: `contracts`**
- Models: `Contract(id: UUID pk, engagement_id: str, raw_text: TextField, source_filename: str|null, razorpay_reference_type: enum[payout, subscription], razorpay_reference_id: str, created_at, updated_at)`; `Clause(id: UUID pk, contract: FK(Contract), sequence_index: int, clause_text: TextField, clause_type: enum[8 labels]|null, classification_confidence: float|null, classification_rationale: str|null, created_at)`.
- `services.py`:
  - `create_contract(*, raw_text: str, engagement_id: str, razorpay_reference_type: str, razorpay_reference_id: str, source_filename: str | None = None) -> Contract`
  - `mark_contract_needs_human_review(*, contract: Contract, reason: str) -> Contract`
- `selectors.py`:
  - `get_contract(*, contract_id: UUID) -> Contract`
  - `list_clauses_for_contract(*, contract: Contract) -> QuerySet[Clause]` (ordered by `sequence_index`)

**New Django app: `pipeline`**
- Models: `ExtractedTerm(id: UUID pk, clause: FK(Clause), term_type: enum[5 types], value_raw: TextField, value_structured: JSONField, extraction_confidence: float, needs_human_review: bool, created_at)`; `AuditLogEntry(id: UUID pk, contract: FK(Contract), clause: FK(Clause, null=True), stage: int, prompt_version: str, llm_response_raw: JSONField, model_name: str, latency_ms: int, created_at)`.
- `services.py`:
  - `segment_contract(*, contract: Contract) -> list[Clause]` — calls `core.claude_client`, validates verbatim spans, writes `Clause` rows and one `AuditLogEntry` (stage=1), calls `contracts.services.mark_contract_needs_human_review` on validation failure.
  - `classify_clause(*, clause: Clause) -> Clause` — writes `clause_type`/`classification_confidence`/`classification_rationale`, applies the confidence and margin gate, writes one `AuditLogEntry` (stage=2).
  - `extract_terms(*, clause: Clause) -> list[ExtractedTerm]` — no-ops for non-payment-bearing clause types, otherwise writes `ExtractedTerm` rows and one `AuditLogEntry` (stage=3).
  - `run_pipeline(*, contract: Contract, from_stage: int = 1) -> None` — orchestrates the three stage functions in order; does not pass data between them except by re-reading from the database, so it can resume at any stage.
- `selectors.py`:
  - `get_audit_trail(*, contract: Contract) -> QuerySet[AuditLogEntry]` (ordered by `stage`, then `created_at`)
  - `list_extracted_terms_for_clause(*, clause: Clause) -> QuerySet[ExtractedTerm]`

**New Django app: `core`** (no models)
- `claude_client.py`: `get_structured_completion(...)`, `quote_is_verbatim(...)` as above.

**Management commands**
- `contracts/management/commands/ingest_contract.py` — reads a file path + engagement metadata from CLI args, calls `contracts.services.create_contract`.
- `pipeline/management/commands/run_pipeline.py` — takes `--contract-id` and optional `--from-stage`, calls `pipeline.services.run_pipeline`.

## Risks / Trade-offs

- **[Risk]** Splitting `contracts` and `pipeline` into two apps for a phase-1-only feature set adds indirection before it pays off. → **Mitigation**: the split is what phase 2 needs anyway (`razorpay_integration` depending on `pipeline` without depending on ingestion concerns); paying the cost now avoids a migration-and-import-rewrite change later.
- **[Risk]** Forcing every Claude call through one `core.claude_client` wrapper makes that module a single point of failure for all three stages. → **Mitigation**: the wrapper does no business logic — retries and schema enforcement only — so a failure there is a genuine upstream (API/network) failure, not a hidden coupling bug; each stage still owns its own retry-then-`needs_human_review` decision.
- **[Risk]** `run_pipeline`'s database-only handoff between stages (no in-memory passing) costs one extra round-trip per stage compared to threading Python objects through. → **Mitigation**: accepted deliberately — this is exactly the property phase 3's human-review resubmission loop needs; contract volumes here are small (tens of clauses), so the extra round-trips are not a real performance concern.

## Migration Plan

Greenfield — `manage.py makemigrations contracts pipeline` produces the initial migrations for this change; there is no existing schema to migrate from and no rollback concern beyond `manage.py migrate contracts pipeline zero` in local dev.
