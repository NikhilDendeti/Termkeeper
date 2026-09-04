## 1. Model and migration

- [ ] 1.1 Add `prev_hash`, `entry_hash` (`CharField(max_length=64, null=True, blank=True)`) and `chain_sequence` (`PositiveBigIntegerField(null=True, blank=True)`) to `pipeline.models.AuditLogEntry`, with a docstring note that a null triple means "written before hash-chain verification existed - exempt" (spec: Pre-existing entries are explicit chain-exempt)
- [ ] 1.2 Run `makemigrations pipeline`, hand-review the generated migration (schema-only, no data migration - see design.md Decision 2), and verify `manage.py migrate` applies cleanly against the current `db.sqlite3` with zero data loss and every existing row left with all three new columns `NULL`
- [ ] 1.3 Update `pipeline/tests/factories.py::AuditLogEntryFactory` only if needed for the new nullable fields (should require no change - confirm existing factory-built rows still default to the exempt null state and every currently-passing test that uses this factory still passes unmodified)

## 2. `core/audit_hash.py` - shared canonical hash function

- [ ] 2.1 Implement `core/audit_hash.py`: `GENESIS_PREV_HASH`, `HASH_SCHEMA_VERSION`, `compute_entry_hash(entry) -> str` exactly per design.md - Decision 3 (canonical `json.dumps(..., sort_keys=True, separators=(",", ":"))`, `sha256(prev_hash + canonical_json)`)
- [ ] 2.2 Write `core/tests/test_audit_hash.py`: assert the same field values always produce the same hash (determinism), assert changing any one hashed field (`stage`, `llm_response_raw`, `prev_hash`, `chain_sequence`, etc.) changes the resulting hash, and assert `llm_response_raw` key-order does not affect the hash (construct two dicts with the same keys/values in different insertion order, confirm identical hash) - spec: entry_hash is computed by one function shared between every writer and the verifier

## 3. `pipeline` write path - the one real write function

- [ ] 3.1 Add `pipeline.selectors.get_chain_tip(*, contract) -> AuditLogEntry | None` returning the highest-`chain_sequence` entry for that contract with a non-null `entry_hash` (or `None`), with a unit test covering: no entries yet, only exempt entries, and a mix of exempt then hashed entries (spec: A mixed contract's chain begins at its first hashed entry)
- [ ] 3.2 Promote `pipeline.services._create_audit_log_entry` to a public `create_audit_log_entry(*, contract, clause, stage, prompt_version, llm_response_raw, model_name, latency_ms) -> AuditLogEntry`, implementing the tip-lookup + `chain_sequence`/`prev_hash` assignment + create + `core.audit_hash.compute_entry_hash` + `entry_hash` update sequence from design.md - Decision 3, all inside one `transaction.atomic()` block using `select_for_update()` on the tip lookup
- [ ] 3.3 Update `segment_contract`, `classify_clause`, and `extract_terms` (the three existing in-file call sites) to call the renamed public function - no behavioral change to their existing arguments
- [ ] 3.4 Write a test proving a contract's first `AuditLogEntry` gets `prev_hash=GENESIS_PREV_HASH`, `chain_sequence=1` (spec: A contract's first hashed entry chains from genesis), and a test proving a second entry for the same contract chains to the first (spec: Later entries chain to the immediately prior entry for the same contract)
- [ ] 3.5 Write a test proving two different contracts' chains never reference each other and each starts its own `chain_sequence` at `1` (spec: Two contracts' chains are independent)
- [ ] 3.6 Run the existing `pipeline/tests/` suite (`test_segmentation.py`, `test_classification.py`, `test_extraction.py`, `test_orchestration.py`, `test_selectors.py`) and confirm every previously-passing assertion still passes with no changes to their expectations about `AuditLogEntry`'s pre-existing fields

## 4. `razorpay_integration` - stage 4 call site

- [ ] 4.1 Delete `razorpay_integration/services.py::_create_audit_log_entry` and update `_generate_mismatch_description`'s one call site to call `pipeline.services.create_audit_log_entry(..., stage=_STAGE_4, prompt_version=_MISMATCH_DESCRIPTION_PROMPT_VERSION, model_name=settings.OPENAI_MODEL, ...)` directly
- [ ] 4.2 Write a test asserting `razorpay_integration.services` no longer defines `_create_audit_log_entry` (e.g. `assert not hasattr(razorpay_integration_services, "_create_audit_log_entry")`) so a future reintroduction of a duplicate write path fails loudly (design.md - Risks)
- [ ] 4.3 Write a test asserting a stage-4 `AuditLogEntry` written via `_generate_mismatch_description` has a non-null `entry_hash` that correctly chains from that contract's most recent prior entry (spec: Every stage's write populates the chain fields)
- [ ] 4.4 Run the existing `razorpay_integration/tests/` suite (`test_mismatch_flagging.py`, `test_pipeline_integration.py` in particular) and confirm every previously-passing assertion still passes

## 5. `risk_scoring` - stage 5 call sites

- [ ] 5.1 Delete `risk_scoring/services.py::_create_audit_log_entry` and update both call sites in `score_clause` (the `needs_human_review` short-circuit path and the main scoring path) to call `pipeline.services.create_audit_log_entry(..., stage=_STAGE_5, prompt_version=..., model_name=settings.OPENAI_MODEL, ...)` directly
- [ ] 5.2 Write a test asserting `risk_scoring.services` no longer defines `_create_audit_log_entry`, mirroring task 4.2
- [ ] 5.3 Write a test asserting both the short-circuit and main-path stage-5 `AuditLogEntry` writes chain correctly, including the case where stage 5 is the first-ever hashed entry for a contract that already has exempt stage 1-4 entries (spec: A mixed contract's chain begins at its first hashed entry)
- [ ] 5.4 Run the existing `risk_scoring/tests/` suite (`test_scoring.py`, `test_pipeline_integration.py` in particular) and confirm every previously-passing assertion still passes

## 6. Verification selector

- [ ] 6.1 Implement `reporting.selectors.verify_audit_chain(*, contract=None) -> AuditChainVerificationResult` per design.md (walks entries in `chain_sequence` order per contract, skips/counts null-hash rows as exempt, recomputes via `core.audit_hash.compute_entry_hash`, detects `entry_hash` mismatches, `prev_hash` mismatches, and `chain_sequence` gaps)
- [ ] 6.2 Write `reporting/tests/test_audit_chain.py` covering: a clean untampered chain passes (spec: Untampered chain verifies clean); a direct field edit on a persisted entry (bypassing `create_audit_log_entry`) is detected (spec: An edited field breaks the chain from that point forward); a deleted mid-chain entry is detected (spec: A deleted entry is detected as a break); a contract with only exempt entries reports `entries_exempt > 0`, `entries_verified == 0`, `passed == True` (spec: A pre-existing entry is reported as exempt, not as passing); scoping to one `contract` never reads or reports on another contract's rows (spec: Two contracts' chains are independent)

## 7. Verification management command

- [ ] 7.1 Implement `report_ui/management/commands/verify_audit_chain.py`, mirroring `verify_guardrail.py`: print a per-contract summary, print any breaks, `raise CommandError(...)` on any break; support an optional `--contract-id` to scope to one contract
- [ ] 7.2 Write `report_ui/tests/test_verify_audit_chain_command.py` mirroring `test_verify_guardrail_command.py`: asserts a clean chain exits zero, asserts a tampered chain raises `CommandError` (non-zero exit) and prints the break's `chain_sequence`

## 8. Report UI and API display touch

- [ ] 8.1 Update `report_ui/views.py::contract_audit_log_view` to also call `reporting_selectors.verify_audit_chain(contract=contract)` and pass the result into the template context
- [ ] 8.2 Update `report_ui/templates/report_ui/contract_audit_log.html` with a chain-integrity section above the entry list (PASS/FAIL styled like `guardrail_verification.html`'s `guardrail-result` classes; an exempt-count note when applicable)
- [ ] 8.3 Write a test in `report_ui/tests/test_contract_audit_log_view.py` (or a new `test_audit_chain_view.py`) asserting the page renders "PASS" for an untampered contract and surfaces a break for a tampered one
- [ ] 8.4 Add `prev_hash`, `entry_hash`, `chain_sequence` to `reporting.serializers.AuditLogEntrySerializer` (all `allow_null=True`), verify the existing audit-log DRF endpoint test(s) still pass and add one asserting the new fields appear in the live response
- [ ] 8.5 Add the matching optional fields to `frontend/src/api/types.ts`'s audit-log entry type and verify `npm run build` in `frontend/` still succeeds with zero TypeScript errors (rendering them in the React UI is not required by this change)

## 9. Verification

- [ ] 9.1 Run the full backend suite (`pytest -q`) and confirm every previously-passing test still passes alongside every new test added above
- [ ] 9.2 Run `mypy` across `core`, `pipeline`, `razorpay_integration`, `risk_scoring`, `reporting`, and `report_ui` and verify zero errors
- [ ] 9.3 Run `openspec validate add-audit-log-hash-chain --strict` and verify it passes before requesting archive
