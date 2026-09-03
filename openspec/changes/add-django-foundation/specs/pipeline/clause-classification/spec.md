## Purpose

Assigns each clause a type from a fixed taxonomy so downstream stages know which clauses carry payment terms worth extracting and which are boilerplate.

## ADDED Requirements

### Requirement: Fixed clause-type taxonomy
The system SHALL classify each clause as exactly one of: payment_schedule, termination, penalty_late_fee, dispute_resolution, auto_renewal, indemnity, other, or needs_human_review.

#### Scenario: Classification restricted to the taxonomy
- **WHEN** a clause is classified
- **THEN** its resulting clause_type is one of the eight defined labels and no other value

### Requirement: Low-confidence classification escalated
The system SHALL classify a clause as needs_human_review, overriding the model's raw label, when its classification confidence falls below the configured threshold or when its top two candidate labels are within the configured margin of each other.

#### Scenario: Confidence below threshold
- **WHEN** a clause's classification confidence is below the configured minimum
- **THEN** the clause's stored clause_type is needs_human_review regardless of which label the model favored

#### Scenario: Two plausible labels too close to call
- **WHEN** a clause's top two candidate labels differ in confidence by less than the configured margin
- **THEN** the clause's stored clause_type is needs_human_review

### Requirement: Classification is auditable
Every classification decision SHALL be traceable to the clause text it was based on and the confidence values that produced it.

#### Scenario: Classification rationale retrievable
- **WHEN** a clause has been classified
- **THEN** the confidence value and a rationale for the assigned clause_type are retrievable for that clause
