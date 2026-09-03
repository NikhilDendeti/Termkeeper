## Purpose

Gives a reviewer a browsable, complete rendering of a contract's `AuditLogEntry` trail in stage order — the concrete, inspectable proof behind the "every AI-produced flag carries its full reasoning chain" guardrail, not just an assertion in documentation.

## ADDED Requirements

### Requirement: Complete audit trail rendered in stage order
The system SHALL render every audit log entry belonging to a contract, ordered by `stage` ascending and then by `created_at` ascending within a stage, with no entry omitted.

#### Scenario: Full trail visible for a contract
- **WHEN** a reviewer opens the audit log page for a contract that has completed stages 1 through N
- **THEN** every audit log entry recorded for that contract is listed, ordered first by stage and then by creation time within a stage

### Requirement: Entry metadata visible without further navigation
Each rendered entry SHALL display its `prompt_version`, `model_name`, and `latency_ms` inline, without requiring the reviewer to open another page or call an API.

#### Scenario: Metadata visible per entry
- **WHEN** a reviewer views the audit log page for a contract with at least one audit log entry
- **THEN** each listed entry shows its prompt_version, model_name, and latency_ms alongside it

### Requirement: Raw model response inspectable per entry
The system SHALL let a reviewer inspect an entry's complete `llm_response_raw` content from the audit log page itself, formatted for readability, without a separate API call or admin login.

#### Scenario: Raw response viewable on demand
- **WHEN** a reviewer chooses to inspect a specific audit log entry on the page
- **THEN** that entry's complete llm_response_raw content is displayed on the same page, formatted for readability

### Requirement: Clause-scoped entries are distinguishable from contract-level entries
Where an audit log entry references a clause, the system SHALL display which clause it belongs to; where an entry has no clause reference, the system SHALL render it as a contract-level entry rather than implying a clause association that does not exist.

#### Scenario: Clause-scoped entry identifies its clause
- **WHEN** an audit log entry has a non-null clause reference
- **THEN** the rendered entry identifies which clause it belongs to

#### Scenario: Contract-level entry shown without a false clause association
- **WHEN** an audit log entry has a null clause reference (for example, a stage 1 segmentation entry)
- **THEN** the rendered entry is displayed as contract-level and does not display a clause association
