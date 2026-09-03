## Purpose

Persists every contract-versus-platform mismatch as a queryable MismatchFlag with a deterministic classification and a quote-grounded description, so downstream risk scoring and reporting can consume mismatches with their full evidence trail already attached.

## ADDED Requirements

### Requirement: Deterministic mismatch classification precedes any LLM involvement
The system SHALL compute whether a mismatch exists, and its mismatch_type, via deterministic code comparison of extracted-term and platform values before any LLM call is made for that comparison; the LLM SHALL NOT be used to decide whether a mismatch exists.

#### Scenario: Mismatch decision made without an LLM call
- **WHEN** a payout-history or subscription-field comparison is evaluated
- **THEN** the mismatch_type and the decision to create a MismatchFlag are determined entirely by deterministic comparison logic, and no core.claude_client call is issued for a comparison that did not deterministically produce a MismatchFlag

### Requirement: Persisted MismatchFlag links term and platform evidence
The system SHALL persist each detected mismatch as a MismatchFlag record linked to the originating ExtractedTerm and, when platform evidence exists, the PlatformRecord it was compared against; platform_record SHALL be null only for a missing_platform_evidence or trigger_condition_unverifiable mismatch.

#### Scenario: Cadence mismatch links both extracted term and platform record
- **WHEN** a cadence_mismatch or amount_mismatch MismatchFlag is created
- **THEN** the resulting MismatchFlag references the ExtractedTerm it was compared from and a non-null platform_record

#### Scenario: Missing-evidence mismatch has no platform record
- **WHEN** a missing_platform_evidence or trigger_condition_unverifiable MismatchFlag is created
- **THEN** the resulting MismatchFlag's platform_record is null

### Requirement: Quote-grounded description generation
The system SHALL generate each MismatchFlag's description via core.claude_client such that the description quotes verbatim both the contract-stated value (expected_value) and the platform-observed value (actual_value), with each quote verified via core.claude_client.quote_is_verbatim against its respective source text before the MismatchFlag is persisted.

#### Scenario: Description quotes both compared values
- **WHEN** a MismatchFlag description is generated for a cadence_mismatch or amount_mismatch
- **THEN** the description contains a verbatim quote drawn from the ExtractedTerm's value_raw text underlying expected_value and a verbatim quote or value drawn from the PlatformRecord payload underlying actual_value, and each quote independently passes quote_is_verbatim against its source

#### Scenario: Unverifiable quote falls back to a deterministic description
- **WHEN** a generated description's quote fails quote_is_verbatim against its source after one retry
- **THEN** the MismatchFlag is persisted with a deterministic, templated description built directly from expected_value and actual_value rather than an unverified LLM-authored quote

### Requirement: Mismatch type restricted to a fixed taxonomy
The system SHALL classify every MismatchFlag as exactly one of: cadence_mismatch, amount_mismatch, missing_platform_evidence, or trigger_condition_unverifiable.

#### Scenario: mismatch_type restricted to the taxonomy
- **WHEN** a MismatchFlag is created
- **THEN** its mismatch_type is one of the four defined labels and no other value

### Requirement: Every MismatchFlag is queryable with its full evidence chain
The system SHALL make each MismatchFlag's full reasoning chain — extracted term, platform evidence (or its absence), and description — retrievable as persisted data, not only as a value embedded in a synchronous pipeline response.

#### Scenario: Mismatch evidence chain is retrievable after the pipeline run completes
- **WHEN** a MismatchFlag created during a prior pipeline run is looked up afterward
- **THEN** its linked ExtractedTerm, its platform_record (or explicit null), and its description are all retrievable from persisted storage without re-running the pipeline
