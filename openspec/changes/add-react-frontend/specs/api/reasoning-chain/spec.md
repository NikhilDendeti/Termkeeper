## Purpose

Exposes a contract's full per-clause reasoning chain as JSON, so a browser-based frontend can render the same clause-by-clause evidence trail that `report_ui`'s server-rendered view already shows.

## ADDED Requirements

### Requirement: Reasoning-chain endpoint
The system SHALL expose a read-only endpoint returning a contract's clauses in sequence order, each with its classification state, extracted terms, linked platform mismatch evidence, and risk assessment (or an explicit absent state for any stage not yet reached).

#### Scenario: Every clause included regardless of state
- **WHEN** a caller requests the reasoning-chain endpoint for a contract
- **THEN** every clause belonging to that contract appears in the response in sequence order, including clauses marked needs_human_review and clauses not yet risk-scored

#### Scenario: Clause with no platform evidence
- **WHEN** a clause has no linked MismatchFlag
- **THEN** its entry's platform evidence list is present and empty, not omitted or null

#### Scenario: Clause not yet risk-scored
- **WHEN** a clause has not yet reached risk scoring
- **THEN** its entry's risk assessment field is explicitly null, not omitted

### Requirement: Unknown contract returns a clear error
The system SHALL return a 404-class response, not a server error, when the requested contract id does not exist.

#### Scenario: Nonexistent contract id
- **WHEN** a caller requests the reasoning-chain endpoint with a contract id that does not exist
- **THEN** the response is a 404-class error identifying the missing contract
