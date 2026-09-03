## Purpose

Lets the user-facing report show which kinds of clauses are driving a contract's risk, closing the gap between the pitch's original claim and what the report actually returned.

## ADDED Requirements

### Requirement: Report includes a per-clause-type severity breakdown
The system SHALL include, in a contract's aggregate report, a breakdown grouping every scored (non-needs_human_review) clause by its clause_type, with the count of clauses and the mean asymmetry_score in that group.

#### Scenario: Breakdown present alongside the overall score
- **WHEN** a contract's aggregate report is retrieved and it has at least one scored clause
- **THEN** the response includes a severity_breakdown_by_clause_type entry for every clause_type that has at least one scored clause, alongside the existing overall_risk_score

#### Scenario: No scored clauses yields an empty breakdown
- **WHEN** a contract has no scored clauses yet
- **THEN** severity_breakdown_by_clause_type is an empty structure, not omitted or an error, consistent with overall_risk_score being null in the same case

### Requirement: Breakdown excludes needs-human-review clauses
The breakdown SHALL exclude clauses whose severity is needs_human_review, consistent with how overall_risk_score already excludes them.

#### Scenario: Needs-human-review clause not counted in any group
- **WHEN** a contract has a clause scored needs_human_review
- **THEN** that clause does not contribute to any clause_type's count or mean asymmetry_score in the breakdown
