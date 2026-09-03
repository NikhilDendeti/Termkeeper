## Purpose

Combines every already-persisted RiskAssessment and MismatchFlag for a contract into a single deterministic, LLM-free overall risk figure and supporting lists, without ever letting one unreviewable clause silently move the headline number.

## ADDED Requirements

### Requirement: Human-review clauses excluded from the score
The system SHALL exclude every clause whose RiskAssessment.severity is needs_human_review from the overall_risk_score calculation's numerator and denominator, and SHALL list those clauses separately in the report's needs_human_review_clauses field.

#### Scenario: Mixed contract excludes unreviewed clauses from the score
- **WHEN** a contract has both scored (non-needs_human_review) clauses and needs_human_review clauses
- **THEN** overall_risk_score is computed using only the scored clauses, and every needs_human_review clause appears in needs_human_review_clauses instead of contributing to the score

#### Scenario: All-unreviewed contract yields no numeric score
- **WHEN** every clause on a contract has RiskAssessment.severity equal to needs_human_review
- **THEN** overall_risk_score is null rather than zero, and every clause appears in needs_human_review_clauses

### Requirement: Fixed severity-to-weight mapping
The system SHALL compute overall_risk_score as the mean, over all non-needs_human_review RiskAssessments for the contract, of a fixed per-severity weight: critical = 1.0, high = 0.75, medium = 0.5, low = 0.25.

#### Scenario: Score reflects the weighted mean
- **WHEN** a contract has exactly one critical RiskAssessment and one low RiskAssessment and no others
- **THEN** overall_risk_score equals 0.625

### Requirement: Deterministic, LLM-free aggregation
The system SHALL compute the aggregate report using only already-persisted RiskAssessment and MismatchFlag rows, issuing no call to the Claude API, and SHALL return byte-identical overall_risk_score and clause orderings across repeated calls against unchanged data.

#### Scenario: Repeated calls agree
- **WHEN** the aggregate report is generated twice in succession for the same contract with no pipeline stage re-run in between
- **THEN** both calls return the same overall_risk_score and the same ordering of ranked flagged clauses

#### Scenario: No model call issued
- **WHEN** the aggregate report is generated for any contract
- **THEN** no request is made to the Claude API during that generation

### Requirement: Mismatches combined into the report
The system SHALL include every MismatchFlag whose ExtractedTerm belongs to a Clause on the contract in the report's platform_mismatches list, each entry identifying its source clause.

#### Scenario: Every contract mismatch is represented
- **WHEN** a contract has MismatchFlag rows against extracted terms on two different clauses
- **THEN** platform_mismatches contains an entry for each MismatchFlag, each identifying its originating clause
