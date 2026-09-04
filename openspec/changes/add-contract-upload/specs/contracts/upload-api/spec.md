## Purpose

Lets a caller create a Contract over HTTP from submitted text, so the frontend (or any other client) can offer self-service contract submission instead of requiring backend CLI access.

## ADDED Requirements

### Requirement: Contract creation endpoint
The system SHALL expose a write endpoint that accepts contract text and engagement/Razorpay metadata and creates a Contract, returning its id on success.

#### Scenario: Valid submission creates a contract
- **WHEN** a caller submits non-empty contract text with engagement_id, razorpay_reference_type, and razorpay_reference_id
- **THEN** the endpoint creates a Contract and returns its id with a 201-class response

#### Scenario: Invalid submission is rejected with a clear reason
- **WHEN** a caller submits a request missing any required field, or with empty contract text
- **THEN** the endpoint rejects it with a 400-class response identifying which field is invalid, and no Contract is created

### Requirement: Endpoint reuses existing validation, does not duplicate it
The endpoint SHALL delegate all creation logic to the existing `contracts.services.create_contract` function rather than re-implementing validation.

#### Scenario: Endpoint behavior matches the CLI path
- **WHEN** the same contract text and metadata are submitted via this endpoint and via the existing `ingest_contract` management command
- **THEN** both produce an equivalent, valid Contract record — no endpoint-specific validation rules exist that the CLI path doesn't also enforce
