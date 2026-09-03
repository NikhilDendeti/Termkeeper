## Purpose

Gives every pipeline stage's decision a persisted, queryable record, so any flag the system later produces can be explained back to its exact model call rather than asserted.

## ADDED Requirements

### Requirement: One audit entry per stage invocation
The system SHALL record one audit log entry for every pipeline stage invocation, including the stage number, the prompt version used, the raw model response, and the resulting latency.

#### Scenario: Audit entry created per stage call
- **WHEN** any pipeline stage — segmentation, classification, or extraction — runs for a contract or clause
- **THEN** exactly one audit log entry is persisted for that invocation

### Requirement: Audit trail queryable per contract
The system SHALL make a Contract's complete audit trail retrievable in stage order.

#### Scenario: Full trail retrievable
- **WHEN** a Contract has completed stages 1 through 3
- **THEN** its audit log entries for all three stages are retrievable together, ordered by stage and then by creation time
