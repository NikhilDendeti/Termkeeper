## Context

See proposal.md - Why. `AuditLogEntry` (`pipeline/models.py`) already exists and is written from exactly three files, each behind its own private `_create_audit_log_entry`-shaped helper, confirmed by reading the current code before writing this design:

- `pipeline/services.py::_create_audit_log_entry` - called from `segment_contract` (stage 1), `classify_clause` (stage 2), `extract_terms` (stage 3).
- `razorpay_integration/services.py::_create_audit_log_entry` - called once, from `_generate_mismatch_description` (stage 4, `_STAGE_4 = 4`).
- `risk_scoring/services.py::_create_audit_log_entry` - called twice, from `score_clause`'s short-circuit path and its main path (stage 5, `_STAGE_5 = 5`).

All three helpers end in the same shape: `AuditLogEntry.objects.create(contract=..., clause=..., stage=..., prompt_version=..., llm_response_raw=..., model_name=settings.OPENAI_MODEL, latency_ms=...)`. They are three independent implementations of the same write, not one shared function - which is exactly the drift risk this design must close, not just for the write itself but for whatever hash math gets added to it.

Two existing ordering facts matter for this design and must not be assumed away:

1. `pipeline.selectors.get_audit_trail` (used by `reporting.selectors.get_full_audit_trail` and `report_ui`'s audit log page) orders `AuditLogEntry` by `("stage", "created_at")`, not by insertion order. `report_ui/tests/test_contract_audit_log_view.py::TestAuditTrailStageOrder` deliberately creates entries out of stage order and asserts the page re-sorts them - i.e., the *display* order is not the *write* order. The hash chain's order must be the real write order, and must not be confused with, or derived from, this display ordering.
2. `AuditLogEntry.id` is a client-generated `uuid.uuid4()` (random, not time-sortable) and `created_at` is `auto_now_add=True` (assigned by Django at save time, not settable by the caller). Neither field is a safe, unambiguous tie-breaker for "which entry came first" on its own.

## Goals / Non-Goals

**Goals:**
- Make it possible to prove, by recomputation from the persisted rows alone, that no `AuditLogEntry` belonging to a given contract's evidence trail was edited or deleted after it was written.
- Reuse the one architectural move that already makes the Razorpay guardrail claim credible: a pure function that recomputes the truth from current data, wrapped by both a CLI command and a live page, never a value that is computed once and then just displayed.
- Collapse the three independent `_create_audit_log_entry` helpers into one real write path, so the hash-chain logic (and the plain fields it wraps) can never drift between stages 1-3, 4, and 5.

**Non-Goals:**
- No change to *what* is logged (still `stage`, `prompt_version`, `llm_response_raw`, `model_name`, `latency_ms`) - only three new columns and the logic to populate/verify them.
- No cryptographic signing, no external anchoring (e.g. publishing chain tips somewhere outside this database) - a self-contained hash chain is sufficient to answer "was this contract's evidence trail edited after the fact," which is the actual question this closes.
- No attempt to retroactively certify rows written before this change shipped - see Decision: Backfill below.

## Decisions

### Decision 1: Chain scope is per-Contract, not global

**Chosen: one independent hash chain per `Contract`**, keyed by `contract_id`, ordered by a new per-contract `chain_sequence` counter (see Decision 3).

Every real consumption path for `AuditLogEntry` today is already scoped to one contract: `pipeline.selectors.get_audit_trail(*, contract)`, `reporting.selectors.get_full_audit_trail(*, contract)`, the `report_ui` audit-log page (`/contracts/<id>/audit-log/`), and the DRF audit-log endpoint all take a single `Contract` and return only its rows. Nobody in this product ever reads "the whole system's audit log" as one artifact - what a reader (a report viewer, an auditor, a judge) actually holds in front of them is one contract's report and wants to know: *was this contract's evidence trail tampered with*. A per-contract chain answers exactly that question, self-contained - anyone can take one contract's `AuditLogEntry` rows, recompute the chain, and get a verdict without needing every other contract that has ever been processed in this system.

A single global chain across every `AuditLogEntry` ever created was considered and rejected for this product, for three reasons:
1. **Wrong grain for the actual claim.** A global chain proves "nothing in this whole database's audit history was reordered," which is a system-operator concern, not what a report reader needs. It does not make any single contract's report more or less trustworthy on its own - a global break caused by contract B's chain tells you nothing about whether contract A's evidence was tampered with, yet a naive verifier would have to treat A as unverifiable too, since one shared chain fails as a whole once broken anywhere.
2. **Contention with no benefit.** Contracts are processed independently (the pipeline runs and resumes per-contract via `run_pipeline(contract=..., from_stage=...)`); a global chain would force every write, across every contract being processed anywhere in the system, to serialize on one shared "tip" value, for a guarantee nothing in this product's usage pattern asks for.
3. **It does not match how integrity is actually consumed.** The existing `verify_guardrail` precedent proves a property of the *source code*, checked once, globally, because the guardrail is a property of the code, not of any one contract. `AuditLogEntry` integrity is a property of one contract's evidence trail, checked per contract, because that is the unit a reader is being asked to trust.

Accepted trade-off: a per-contract chain cannot, by itself, prove that no *entire contract's chain* was deleted wholesale (an attacker with DB write access could delete every `AuditLogEntry` row for one contract and no other contract's chain would show it). This is the same residual risk any partitioned tamper-evidence scheme accepts and is not unique to this design - closing it would require an append-only write log or external anchoring, both out of scope (see Non-Goals). What per-contract scoping does guarantee is exactly the claim this product needs: *given the AuditLogEntry rows presented for a contract, prove whether the values in them (and their presence, in the order that ran) match what a continuous chain computed from those same rows would produce.*

### Decision 2: Existing rows are marked chain-exempt, never silently backfilled

**Chosen: do not compute hashes for `AuditLogEntry` rows that existed before this change ships.** The migration adds three nullable columns only; every pre-existing row keeps `prev_hash = NULL`, `entry_hash = NULL`, `chain_sequence = NULL`. That null-triple *is* the exemption marker - no separate boolean flag is added (see "why no boolean" below). `verify_audit_chain` (design below) treats a null-hash row as **exempt**, a third state distinct from both PASS and FAIL, and reports it as such rather than folding it into either.

A data migration that computed `entry_hash` for every existing row retroactively was considered and rejected. The reasoning: a hash computed *today* over a row's *current* field values proves only that the row has not changed *since the moment the backfill ran* - it proves nothing about whether the row was edited between the moment the original LLM call actually happened and the moment this backfill migration runs. Presenting a backfilled hash as part of the same unbroken chain as genuinely write-time-hashed entries would silently overstate what is actually known: a reader (or the verify command's PASS output) would have no way to tell "this entry's integrity has been provable since the instant it was created" from "this entry's integrity has only been provable since some later migration ran, and anything could have happened to it before that." Manufacturing that hash would make the tamper-evidence claim itself less honest, which defeats the purpose of adding it. Silently ignoring the question entirely (e.g. leaving the columns nullable but never surfacing that some rows are unhashed) was also rejected, for the same reason in the opposite direction: a report or CLI run that only ever says "PASS" without distinguishing verified-from-birth entries from exempt legacy ones would let a reader assume more was proven than actually was.

Why a null-hash convention instead of a separate `is_chain_exempt` boolean: a boolean field is redundant state that has to be kept in sync with whether `entry_hash` is actually null, and every place that reads it would have to trust that the two never drift apart (exactly the kind of duplicated-source-of-truth risk this whole design is trying to eliminate from the write path). `entry_hash IS NULL` is already an unambiguous, single-source-of-truth signal for "this row predates hash-chain verification" - no second field can say anything the first doesn't already say.

**Mixed contracts.** A `Contract` fully processed before this change ships has every `AuditLogEntry` exempt. A `Contract` reprocessed or resumed (`run_pipeline(..., from_stage=N)`) after this change ships can end up with some exempt (pre-existing) rows and some hashed (newly written) rows in `chain_sequence` order. This is handled explicitly, not as an edge case bolted on afterward: **a contract's chain begins at the first row (by `chain_sequence`, i.e. write order) that has a non-null `entry_hash`; that row's `prev_hash` is `GENESIS_PREV_HASH` regardless of how many exempt rows precede it.** Exempt rows before that point are counted and reported, never treated as a break and never treated as verified.

### Decision 3: Canonical hash input, chain ordering, and the single shared function

**Ordering: a new `chain_sequence` field, not `created_at`.** `created_at`'s microsecond resolution is not a rigorous ordering guarantee (a synchronous batch write - e.g. a future bulk-resubmission path - could plausibly produce a tie), and `id` (random UUID4) cannot break a tie meaningfully. `AuditLogEntry` gains `chain_sequence: PositiveBigIntegerField(null=True, blank=True)`, assigned per-contract, starting at `1` for that contract's first hashed entry. It is the authoritative write-order key for both writing and verifying the chain - display ordering (`get_audit_trail`'s `("stage", "created_at")`) is untouched and remains purely a presentation concern.

**The write sequence**, entirely inside `pipeline.services.create_audit_log_entry` (see below), wrapped in one `transaction.atomic()` block (this project's existing convention for multi-step writes, e.g. `segment_contract`, `extract_terms`):
1. `tip = pipeline.selectors.get_chain_tip(contract=contract)` - the current highest-`chain_sequence` entry for this contract that has a non-null `entry_hash` (`select_for_update()` inside the same transaction, so concurrent writers for the same contract cannot compute the same tip twice).
2. `prev_hash = tip.entry_hash if tip else core.audit_hash.GENESIS_PREV_HASH`; `chain_sequence = (tip.chain_sequence + 1) if tip else 1`.
3. `entry = AuditLogEntry.objects.create(contract=..., clause=..., stage=..., prompt_version=..., llm_response_raw=..., model_name=..., latency_ms=..., prev_hash=prev_hash, chain_sequence=chain_sequence)` - `entry_hash` is left unset here. This INSERT is also where Django assigns `entry.id` (client-side, before the INSERT) and `entry.created_at` (server-side `auto_now_add`, but returned on the same Python object with no extra query) - both are only reliably known once this row exists, which is why hashing happens as a second step rather than being computed before the row is created.
4. `entry.entry_hash = core.audit_hash.compute_entry_hash(entry)`; `entry.save(update_fields=["entry_hash"])`.

Because both steps run inside one `transaction.atomic()` block, no reader ever observes a persisted row with `prev_hash`/`chain_sequence` set but `entry_hash` still null.

**`core/audit_hash.py`** (new, no models - same "shared, model-free utility" role `core/llm_client.py` already plays for the pipeline):

```python
GENESIS_PREV_HASH = "0" * 64  # 64 hex chars, same length as a real digest
HASH_SCHEMA_VERSION = 1

def compute_entry_hash(entry: AuditLogEntry) -> str:
    payload = {
        "hash_schema_version": HASH_SCHEMA_VERSION,
        "id": str(entry.id),
        "contract_id": str(entry.contract_id),
        "clause_id": str(entry.clause_id) if entry.clause_id else None,
        "stage": entry.stage,
        "prompt_version": entry.prompt_version,
        "llm_response_raw": entry.llm_response_raw,
        "model_name": entry.model_name,
        "latency_ms": entry.latency_ms,
        "created_at": entry.created_at.isoformat(),
        "chain_sequence": entry.chain_sequence,
    }
    canonical_json = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256((entry.prev_hash + canonical_json).encode("utf-8")).hexdigest()
```

This is exactly `entry_hash = sha256(prev_hash + canonical_serialization_of(this entry's other fields))` per the brief: `prev_hash` is prepended as a raw string to the canonical JSON bytes, not embedded inside the JSON object, so the formula is literally string concatenation followed by one hash - nothing about the algorithm is implicit. `sort_keys=True` + fixed `separators` make the JSON byte-for-byte deterministic regardless of dict insertion order (Python's dict field order does vary across code paths - `llm_response_raw` in particular is parsed JSON from an LLM API response). `hash_schema_version` is included in the hashed payload itself: if a future change ever needs to add or remove a hashed field, it must bump this constant deliberately, which changes every subsequently-computed hash in a visible, intentional way rather than silently reinterpreting old hashes under new rules.

**Single shared function, used identically by writer and verifier.** `pipeline.services.create_audit_log_entry` calls `core.audit_hash.compute_entry_hash` to produce the value it stores; `reporting.selectors.verify_audit_chain` (below) calls the exact same function to produce the value it compares against what is stored. Neither reimplements the formula. This is the concrete answer to "what stops the writer and the verifier from drifting apart" - they are not two implementations kept in sync by convention, they are one function called from two places.

## The verification command

`reporting.selectors.verify_audit_chain(*, contract: Contract | None = None) -> AuditChainVerificationResult`, mirroring `scan_razorpay_guardrail`'s shape exactly (a frozen dataclass result; a `passed: bool`; live recomputation on every call, nothing cached or stored):

```python
@dataclass(frozen=True)
class AuditChainBreak:
    contract_id: uuid.UUID
    entry_id: uuid.UUID
    chain_sequence: int
    reason: str  # "entry_hash_mismatch" | "prev_hash_mismatch" | "chain_sequence_gap"

@dataclass(frozen=True)
class AuditChainVerificationResult:
    passed: bool
    contracts_checked: int
    entries_verified: int
    entries_exempt: int
    breaks: list[AuditChainBreak] = field(default_factory=list)
```

For each contract in scope (all contracts, or just `contract` if given): fetch its `AuditLogEntry` rows ordered by `chain_sequence` (nulls last, i.e. exempt rows sort after every hashed row - they are never interleaved with the real chain by construction, since `chain_sequence` is only ever assigned starting from the first hashed write). Count and skip null-hash rows as exempt. Walk the remaining rows in `chain_sequence` order (which must be gap-free starting at 1 for that contract's first hashed entry - a gap is itself a break, since chain_sequence increments are the only thing standing between "entries deleted" and "entries missing"); for each, recompute `core.audit_hash.compute_entry_hash(entry)` and compare to the stored `entry_hash`, and confirm `entry.prev_hash` equals the previous entry's `entry_hash` (or `GENESIS_PREV_HASH` for the first). Any mismatch is a `AuditChainBreak`; `passed` is `True` only when `breaks` is empty across every contract checked - exempt entries never affect `passed`.

`report_ui/management/commands/verify_audit_chain.py` mirrors `verify_guardrail.py` line for line in structure: call the selector, print a per-contract summary (contracts checked, entries verified, entries exempt), print each break if any, `raise CommandError(...)` (non-zero exit) when `passed` is `False`. Optional `--contract-id <uuid>` scopes to one contract for local debugging; omitted, it checks every contract - suitable for CI the same way `verify_guardrail` already is.

**UI touch.** `report_ui/views.py::contract_audit_log_view` gains one more selector call: `chain_result = reporting_selectors.verify_audit_chain(contract=contract)`, passed into the existing template context. `contract_audit_log.html` gains a small section above the entry list - "Chain integrity: PASS" / "Chain integrity: N break(s) found" / an exempt-count note when `entries_exempt > 0` - styled the same way `guardrail_verification.html` already renders its PASS/FAIL result (`guardrail-result guardrail-pass` / `guardrail-fail` classes reused, not reinvented).

## Risks / Trade-offs

- **[Risk]** Computing a hash chain adds one extra `SELECT ... FOR UPDATE` and one extra `UPDATE` per `AuditLogEntry` write. → **Mitigation**: negligible - this product writes tens of audit entries per contract, synchronously, in an already-multi-query pipeline (each stage already makes an LLM call taking hundreds of milliseconds); two more small local SQLite queries per entry is not a measurable cost.
- **[Risk]** The real risk is not performance, it is *drift*: any future edit to one of the (formerly three, now one) write call sites that bypasses `pipeline.services.create_audit_log_entry` - or any future edit to `core.audit_hash.compute_entry_hash` that isn't mirrored on the verify side - silently breaks the tamper-evidence guarantee without any test failing loudly. → **Mitigation**: this is exactly why the design collapses three private per-app helpers into one public function, and why the verifier imports and calls that same `core.audit_hash.compute_entry_hash` rather than reimplementing the formula - there is structurally only one place either piece of logic can live. Task list includes a test asserting `razorpay_integration.services` and `risk_scoring.services` no longer define their own `_create_audit_log_entry` (i.e. the old duplicate helpers are actually gone, not merely unused) so a future re-introduction of a bypass is caught by a failing test, not just a design-doc rule.
- **[Risk]** `hash_schema_version` bumps are a manual discipline, not enforced by anything. → **Mitigation**: accepted - the same is true of `prompt_version` and `TermType`/`ClauseType` taxonomy changes elsewhere in this codebase; this project's convention is a versioned constant plus a code comment at the point of use, not a runtime enforcement mechanism, and this change follows that existing convention rather than inventing a new one.
- **[Risk]** A per-contract chain (Decision 1) cannot detect whole-contract chain deletion. → **Mitigation**: explicitly accepted, see Decision 1 - out of scope for what this product needs to prove; not a hidden gap, a named and justified one.

## Migration Plan

One schema migration (`pipeline/migrations/000X_auditlogentry_hash_chain.py`): add `prev_hash` (`CharField(max_length=64, null=True, blank=True)`), `entry_hash` (`CharField(max_length=64, null=True, blank=True)`), `chain_sequence` (`PositiveBigIntegerField(null=True, blank=True)`) to `AuditLogEntry`. No data migration. Every existing row is left exactly as-is (all three new columns `NULL`), which is by construction the chain-exempt state - see Decision 2. Rollout order: (1) migration + model fields, verify `manage.py migrate` applies cleanly against the existing `db.sqlite3` with no data loss; (2) `core/audit_hash.py` + its unit tests, in isolation, before anything calls it; (3) promote `pipeline.services.create_audit_log_entry` to public and wire it to `core.audit_hash`, verify stages 1-3 still pass every existing test; (4) point `razorpay_integration.services` and `risk_scoring.services` at the shared function and delete their private duplicates, verify stage 4/5 tests still pass; (5) `reporting.selectors.verify_audit_chain` + the management command + the `report_ui` display touch, last, once the write side is proven correct - mirroring how `close-pitch-accuracy-gaps` sequenced "prove the exporter correct, then generate the real artifact."
