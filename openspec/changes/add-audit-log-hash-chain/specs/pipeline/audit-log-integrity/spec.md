## Purpose

Makes every persisted `AuditLogEntry` tamper-evident: any edit to a past entry's fields, or any entry deleted or inserted out of order, is deterministically detectable by recomputation from the persisted rows alone - not merely asserted by the fact that a row exists.

## ADDED Requirements

### Requirement: Hash-chain fields populated on every AuditLogEntry write
The system SHALL populate `prev_hash`, `entry_hash`, and `chain_sequence` on every `AuditLogEntry` created after this capability ships, regardless of which pipeline stage writes it, via one shared write function used by every call site.

#### Scenario: Every stage's write populates the chain fields
- **WHEN** an `AuditLogEntry` is created by stage 1, 2, or 3 (`pipeline.services`), stage 4 (`razorpay_integration.services`), or stage 5 (`risk_scoring.services`)
- **THEN** the resulting row has a non-null `prev_hash`, `entry_hash`, and `chain_sequence`, and `entry_hash` equals `core.audit_hash.compute_entry_hash` recomputed from that row's own persisted fields

#### Scenario: A contract's first hashed entry chains from genesis
- **WHEN** the first `AuditLogEntry` with a non-null `entry_hash` is written for a given Contract
- **THEN** its `prev_hash` equals `core.audit_hash.GENESIS_PREV_HASH` and its `chain_sequence` is `1`

#### Scenario: Later entries chain to the immediately prior entry for the same contract
- **WHEN** a second (or later) `AuditLogEntry` is written for a Contract that already has at least one hashed entry
- **THEN** the new entry's `prev_hash` equals the immediately preceding entry's `entry_hash` (by `chain_sequence` order) for that same contract, and its `chain_sequence` is exactly one greater

### Requirement: Chain scoped per Contract
The system SHALL maintain one independent hash chain per Contract; entries belonging to different contracts SHALL NOT be linked to one another and a break confined to one contract's chain SHALL NOT be reported against any other contract.

#### Scenario: Two contracts' chains are independent
- **WHEN** two different Contracts each have their own hashed `AuditLogEntry` rows
- **THEN** verifying one contract's chain does not read, require, or depend on the other contract's rows, and each contract's `chain_sequence` starts at `1` independently

### Requirement: Chain tampering is deterministically detectable via verification
The system SHALL provide a verification path (`reporting.selectors.verify_audit_chain`, exposed via the `verify_audit_chain` management command) that recomputes each in-scope entry's expected hash from its currently persisted fields and reports a pass/fail result live, never a cached or stored verdict.

#### Scenario: Untampered chain verifies clean
- **WHEN** `verify_audit_chain` runs against a contract whose hashed entries have not been altered since they were written
- **THEN** the result's `passed` is `True` and `breaks` is empty for that contract

#### Scenario: An edited field breaks the chain from that point forward
- **WHEN** any hashed field (for example `llm_response_raw` or `stage`) of a previously-written `AuditLogEntry` is modified directly, without going through `pipeline.services.create_audit_log_entry`
- **THEN** `verify_audit_chain` reports a break at that entry's `chain_sequence`, because its stored `entry_hash` no longer equals the hash recomputed from its current field values

#### Scenario: A deleted entry is detected as a break
- **WHEN** a hashed `AuditLogEntry` that is not the last entry in its contract's chain is deleted
- **THEN** `verify_audit_chain` reports a break, because the next remaining entry's `prev_hash` no longer matches any entry actually present in the chain (or the `chain_sequence` sequence for that contract is no longer gap-free)

### Requirement: Pre-existing entries are explicit chain-exempt, never silently counted as verified
The system SHALL represent any `AuditLogEntry` written before this capability existed (identified by a null `entry_hash`) as explicitly exempt from chain verification, distinct from both a pass and a fail, and SHALL NOT compute or infer a hash for such a row after the fact.

#### Scenario: A pre-existing entry is reported as exempt, not as passing
- **WHEN** `verify_audit_chain` runs against a Contract whose `AuditLogEntry` rows include one written before this capability shipped (null `prev_hash`/`entry_hash`/`chain_sequence`)
- **THEN** that entry is counted in `entries_exempt`, is excluded from `entries_verified` and from `breaks`, and the overall `passed` result for that contract is unaffected by its presence

#### Scenario: A mixed contract's chain begins at its first hashed entry
- **WHEN** a Contract has one or more chain-exempt entries followed by entries written after this capability shipped
- **THEN** the first entry with a non-null `entry_hash` has `prev_hash` equal to `core.audit_hash.GENESIS_PREV_HASH` and `chain_sequence` equal to `1`, regardless of how many exempt entries precede it, and the exempt entries are never treated as part of the hashed chain

### Requirement: entry_hash is computed by one function shared between every writer and the verifier
The system SHALL compute `entry_hash` using exactly one function (`core.audit_hash.compute_entry_hash`), called identically by every write path and by `verify_audit_chain`; no write path or verification path SHALL reimplement the hash formula independently.

#### Scenario: Writer and verifier agree by construction
- **WHEN** `pipeline.services.create_audit_log_entry` computes and stores an `entry_hash`, and `verify_audit_chain` later recomputes the expected hash for that same row
- **THEN** both computations call `core.audit_hash.compute_entry_hash` and, for an untampered row, produce identical results
