## 1. Project scaffold

- [x] 1.1 Create the Django project (`config/` with `base.py`/`local.py`/`production.py` settings) and verify `manage.py check` runs cleanly
- [x] 1.2 Add `pyproject.toml` (ruff + mypy config), `pytest.ini` (pytest-django, `DJANGO_SETTINGS_MODULE=config.local`), and `.env.example`, and verify `python manage.py migrate` succeeds against the local SQLite database with no external service running
- [x] 1.3 Add core dependencies (`django`, `djangorestframework`, `anthropic`, `pytest`, `pytest-django`, `factory_boy`, `ruff`, `mypy`) to `pyproject.toml` and verify `pip install -e .` (or equivalent) completes with no conflicts

## 2. `core` app — shared Claude client

- [x] 2.1 Create the `core` app (no models) and register it in `INSTALLED_APPS`, verify `manage.py check` still passes
- [x] 2.2 Implement `core/claude_client.py::get_structured_completion` enforcing tool-use/JSON-schema output, and write a unit test that asserts a malformed/non-schema-conforming mock response raises rather than returning silently
- [x] 2.3 Implement `core/claude_client.py::quote_is_verbatim` and write unit tests for an exact-match quote, a paraphrased quote (must fail), and a quote with trailing whitespace differences

## 3. `contracts` app — models and ingestion

- [x] 3.1 Create the `contracts` app with the `Contract` and `Clause` models per design.md, run `makemigrations contracts`, hand-review the generated migration, and verify `manage.py migrate` applies it cleanly
- [x] 3.2 Implement `contracts/services.py::create_contract` and `mark_contract_needs_human_review`, with unit tests covering the two proposal.md/spec scenarios: valid contract submitted, and missing razorpay reference rejected
- [x] 3.3 Implement `contracts/selectors.py::get_contract` and `list_clauses_for_contract`, with a unit test asserting clauses return ordered by `sequence_index`
- [x] 3.4 Implement the `ingest_contract` management command and verify it creates a `Contract` row when run against a sample contract file

## 4. `pipeline` app — stage 1: segmentation

- [x] 4.1 Create the `pipeline` app with the `ExtractedTerm` and `AuditLogEntry` models per design.md, run `makemigrations pipeline`, hand-review, and verify `manage.py migrate` applies cleanly
- [x] 4.2 Implement `pipeline/services.py::segment_contract`, and write a test proving every returned clause's text is found verbatim in the source contract (spec: Verbatim clause extraction)
- [x] 4.3 Write a test proving a clause with sub-bullets under one heading segments as a single `Clause` row (spec: Multi-topic clauses stay whole)
- [x] 4.4 Write a test that mocks a non-verbatim model response on both attempts and asserts the Contract is marked `needs_human_review` with no `Clause` persisted for that span (spec: Segmentation failure is escalated)
- [x] 4.5 Verify one `AuditLogEntry` (stage=1) is created per `segment_contract` call

## 5. `pipeline` app — stage 2: classification

- [x] 5.1 Implement `pipeline/services.py::classify_clause` restricted to the 8-label taxonomy, with a test asserting an out-of-taxonomy label is never persisted (spec: Fixed clause-type taxonomy)
- [x] 5.2 Implement the confidence-threshold and confidence-margin gates, with tests for both: below-threshold confidence, and two candidates within the configured margin (spec: Low-confidence classification escalated)
- [x] 5.3 Verify classification confidence and rationale are retrievable per clause after classification (spec: Classification is auditable)
- [x] 5.4 Verify one `AuditLogEntry` (stage=2) is created per `classify_clause` call

## 6. `pipeline` app — stage 3: term extraction

- [x] 6.1 Implement `pipeline/services.py::extract_terms` scoped to `payment_schedule`/`penalty_late_fee`/`auto_renewal` clauses, with a test asserting no `ExtractedTerm` is created for a `termination` clause (spec: Extraction scoped to payment-bearing clause types)
- [x] 6.2 Write a test asserting a qualitatively-stated term leaves numeric fields unset rather than guessed (spec: Only stated values are extracted)
- [x] 6.3 Write a test asserting a formula-based term (for example a compounding percentage) is marked `needs_human_review` with its raw text preserved (spec: Low-confidence or unparseable extraction escalated)
- [x] 6.4 Verify an `ExtractedTerm` retains a traceable reference to its source clause and verbatim value span (spec: Extracted term traceable to its clause)
- [x] 6.5 Verify one `AuditLogEntry` (stage=3) is created per `extract_terms` call

## 7. Orchestration and audit trail

- [x] 7.1 Implement `pipeline/services.py::run_pipeline` (stages 1-3, `--from-stage` support) reading/writing only via the database between stages, and verify a full run against a sample contract produces `Clause`, `ExtractedTerm`, and `AuditLogEntry` rows end to end
- [x] 7.2 Implement `pipeline/selectors.py::get_audit_trail` and `list_extracted_terms_for_clause`, with a test asserting a contract's full audit trail is retrievable ordered by stage then creation time (spec: Audit trail queryable per contract)
- [x] 7.3 Implement the `run_pipeline` management command (`--contract-id`, `--from-stage`) and verify it resumes correctly from stage 2 on a contract that already has `Clause` rows

## 8. Verification

- [x] 8.1 Run the full test suite for `core`, `contracts`, and `pipeline` and verify all tests pass
- [x] 8.2 Run `mypy` across the three apps and verify no type errors
- [x] 8.3 Run `openspec validate add-django-foundation --strict` and verify it passes before requesting archive
