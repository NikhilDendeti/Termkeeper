## Purpose

Exposes a contract's full risk report and audit trail as an externally callable surface — a DRF endpoint and an equivalent CLI command — so the same computed content is reachable both programmatically and operationally with no drift between the two.

## ADDED Requirements

### Requirement: Retrieve-only report endpoint
The system SHALL expose a read endpoint that, given a contract identifier, returns that contract's overall_risk_score, ranked flagged clauses, platform mismatches, needs_human_review_clauses, and suggested rewrites.

#### Scenario: Existing contract returns its report
- **WHEN** a client requests the report for a contract that has completed scoring
- **THEN** the response includes overall_risk_score, the ranked flagged-clause list, platform_mismatches, and needs_human_review_clauses

#### Scenario: Unknown contract is rejected
- **WHEN** a client requests the report for a contract identifier that does not exist
- **THEN** the system responds with a not-found error and no report body

### Requirement: Audit trail exposed through the same surface
The system SHALL make a contract's full audit trail (every AuditLogEntry across all pipeline stages) retrievable through the report surface, ordered from earliest to latest.

#### Scenario: Audit trail includes every stage
- **WHEN** a client requests the audit trail for a contract that has been through segmentation, classification, extraction, cross-check, and scoring
- **THEN** the response includes entries from every one of those stages, ordered oldest first

### Requirement: Identical content between API and CLI
The system SHALL return equivalent report content — the same fields and the same values — from the DRF endpoint and the report_contract management command for the same contract.

#### Scenario: CLI and API agree
- **WHEN** the report for the same contract is fetched once via the DRF endpoint and once via the CLI with --format json
- **THEN** every field present in one response is present with the same value in the other

### Requirement: CLI format parity and validation
The system SHALL support --format json and --format md on the report_contract command, each rendering the same underlying report data, and SHALL reject any other --format value without producing partial output.

#### Scenario: Markdown rendering matches JSON content
- **WHEN** the same contract's report is rendered with --format md and --format json
- **THEN** every clause, mismatch, and score present in the JSON output is represented in the markdown output

#### Scenario: Unsupported format is rejected cleanly
- **WHEN** report_contract is invoked with an unsupported --format value
- **THEN** the command exits with an error and writes no report output

### Requirement: Read-only report surface
The system SHALL NOT create, update, or delete any Contract, Clause, ExtractedTerm, PlatformRecord, MismatchFlag, or RiskAssessment record as a side effect of serving the report endpoint, the audit-trail endpoint, or the report_contract command.

#### Scenario: Repeated report requests leave data unchanged
- **WHEN** the report and audit-trail surfaces are each invoked multiple times in succession for the same contract
- **THEN** the row counts for Contract, Clause, ExtractedTerm, PlatformRecord, MismatchFlag, and RiskAssessment are unchanged compared to before those invocations
