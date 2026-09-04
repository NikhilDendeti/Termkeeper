## Purpose

Lets a caller trigger the existing pipeline against a specific contract over HTTP, so a submission made through the upload endpoint can actually be analyzed without backend CLI access, while handling the real possibility of a mid-run provider failure gracefully rather than losing the caller's context.

## ADDED Requirements

### Requirement: Synchronous pipeline trigger endpoint
The system SHALL expose an endpoint that runs the existing pipeline against a given contract id and returns the resulting aggregate report on success.

#### Scenario: Successful analysis returns the report
- **WHEN** a caller triggers analysis for a contract that exists and the pipeline completes without error
- **THEN** the endpoint returns the contract's aggregate report (the same shape the existing report endpoint already returns)

#### Scenario: Unknown contract returns a clear error
- **WHEN** a caller triggers analysis for a contract id that does not exist
- **THEN** the endpoint returns a 404-class error identifying the missing contract, and does not attempt to run the pipeline

### Requirement: Mid-run failure is reported, not silently swallowed or a bare server error
The system SHALL catch a pipeline failure during an HTTP-triggered run and return a structured error response distinguishing "a real error occurred" from a generic failure, and SHALL NOT lose or roll back whatever partial progress the pipeline already persisted before the failure.

#### Scenario: Provider error mid-run
- **WHEN** the pipeline fails partway through (for example, the LLM provider returns a rate-limit or authentication error) after already persisting some clauses, terms, or assessments
- **THEN** the endpoint returns an error response that names the contract id and states that partial progress exists, rather than a bare 500 with no context, and every row the pipeline wrote before the failure remains in the database unchanged

### Requirement: Endpoint does not modify pipeline behavior
The endpoint SHALL call the existing `pipeline.services.run_pipeline` function unmodified — no endpoint-specific pipeline logic, retry behavior, or threshold exists that the CLI path (`manage.py run_pipeline`) doesn't also have.

#### Scenario: Endpoint and CLI produce equivalent results
- **WHEN** the same contract is analyzed via this endpoint and, separately, via the `run_pipeline` management command
- **THEN** both produce equivalent Clause/ExtractedTerm/RiskAssessment/AuditLogEntry state for that contract, modulo the inherent non-determinism of live model calls
