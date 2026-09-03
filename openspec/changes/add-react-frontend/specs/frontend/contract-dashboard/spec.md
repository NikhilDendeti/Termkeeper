## Purpose

Defines what a person can see and do in the standalone frontend, independent of how it's implemented — the externally observable behavior a browser user relies on.

## ADDED Requirements

### Requirement: Contract list is the landing view
The frontend SHALL show, as its first screen, the list of ingested contracts with each one's headline risk status visible without further navigation.

#### Scenario: No contracts yet
- **WHEN** a user opens the frontend before any contract has been ingested
- **THEN** the frontend shows an explicit empty state, not a blank screen or an unexplained error

### Requirement: Contract detail shows the full reasoning chain
Selecting a contract SHALL show every one of its clauses in sequence order, each with its classification, extracted terms, platform evidence, and risk verdict — or an explicit "not yet reviewed" / "no platform evidence" state where a stage hasn't run.

#### Scenario: Needs-human-review clause visibly distinct
- **WHEN** a contract detail view renders a clause whose classification or risk state is needs_human_review
- **THEN** that clause is visibly and textually distinguished from a clause carrying a scored severity, never presented as if it had been reviewed

### Requirement: Audit trail is reachable per contract
From a contract's detail view, a user SHALL be able to see that contract's full audit log trail in stage order.

#### Scenario: Audit entry detail visible
- **WHEN** a user views a contract's audit trail
- **THEN** each entry's stage, prompt version, model name, and latency are visible, and the raw model response is inspectable without leaving the page

### Requirement: Guardrail status is visible
The frontend SHALL show the live guardrail-verification result, including scanned files and any violation evidence, reachable from the main navigation.

#### Scenario: Guardrail check surfaces a clear pass or fail
- **WHEN** a user views the guardrail status
- **THEN** the page shows an unambiguous pass or fail state, never an intermediate or silent state

### Requirement: Network and error states are handled visibly
The frontend SHALL show a visible loading state while a request is in flight and a visible, specific error state when a request fails — never a silent failure or an indefinite spinner with no explanation.

#### Scenario: Backend unreachable
- **WHEN** the backend API is unreachable when the frontend requests contract data
- **THEN** the frontend shows an explicit error message rather than an empty or frozen screen
