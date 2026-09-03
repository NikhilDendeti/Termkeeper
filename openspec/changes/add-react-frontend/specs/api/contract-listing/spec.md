## Purpose

Gives a frontend a single endpoint to discover which contracts exist and their headline risk status, so it can render a dashboard list without a caller having to already know a contract's id.

## ADDED Requirements

### Requirement: Contract list endpoint
The system SHALL expose a read-only endpoint that returns every ingested Contract, each with enough summary data (id, engagement_id, razorpay_reference_type, overall_risk_score, needs_human_review clause count, created_at) to render in a list without a further request per contract.

#### Scenario: Contracts returned newest first
- **WHEN** a caller requests the contract list endpoint
- **THEN** every ingested Contract is present in the response, ordered newest-created first

#### Scenario: Empty project returns an empty list
- **WHEN** a caller requests the contract list endpoint before any contract has been ingested
- **THEN** the response is a successful empty list, not an error

### Requirement: Summary reflects current pipeline state
Each contract's summary SHALL reflect its aggregate risk report as currently computed, including when scoring has not yet run for any clause.

#### Scenario: Contract with no scored clauses yet
- **WHEN** a Contract has been ingested but its pipeline has not reached risk scoring
- **THEN** its list entry's overall_risk_score is null rather than a fabricated value, consistent with reporting's aggregate-report behavior
