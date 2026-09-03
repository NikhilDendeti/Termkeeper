## Purpose

Scores every classified Clause — not only those carrying extracted payment terms — for severity and directional asymmetry, producing a fully quote-grounded explanation so no risk flag reaches a user without traceable evidence in the contract text itself.

## ADDED Requirements

### Requirement: Coverage of every classified clause
The system SHALL produce exactly one RiskAssessment for every Clause on a contract that has completed classification (stage 2), regardless of whether that clause has any associated ExtractedTerm rows.

#### Scenario: Non-payment clause scored on text alone
- **WHEN** a Clause is classified as termination, dispute_resolution, indemnity, or other and has zero associated ExtractedTerm rows
- **THEN** the system produces a RiskAssessment for that clause derived from the clause text alone

#### Scenario: One assessment per clause
- **WHEN** stage 5 scoring is run twice in succession for the same Clause
- **THEN** the clause has exactly one current RiskAssessment after both runs, not two

### Requirement: Fixed severity taxonomy
The system SHALL assign every RiskAssessment exactly one severity value from: low, medium, high, critical, or needs_human_review, and no other value.

#### Scenario: Severity restricted to the taxonomy
- **WHEN** a RiskAssessment is created for any clause
- **THEN** its severity field is one of the five defined labels and no other value

### Requirement: Bounded asymmetry score
The system SHALL constrain every RiskAssessment's asymmetry_score to the closed interval [-1, 1], where the sign indicates which party the clause's obligation, penalty, or notice burden favors and the magnitude indicates how one-sided that burden is.

#### Scenario: Asymmetry score within bounds
- **WHEN** a RiskAssessment is created
- **THEN** its asymmetry_score is greater than or equal to -1 and less than or equal to 1

### Requirement: Severity determined by asymmetry, clause-type criticality, and mismatch linkage
The system SHALL derive each non-needs_human_review RiskAssessment's severity as a function of the magnitude of its asymmetry_score, a fixed criticality weighting for the clause's clause_type, and whether the clause's extracted terms have any MismatchFlag linked from stage 4.

#### Scenario: Higher asymmetry never lowers severity
- **WHEN** two clauses share the same clause_type and mismatch-linkage state but one has a larger absolute asymmetry_score than the other
- **THEN** the clause with the larger absolute asymmetry_score has a severity in the same band or higher, never lower

#### Scenario: Confirmed mismatch raises or holds severity
- **WHEN** two clauses share the same clause_type and asymmetry_score but only one has a MismatchFlag linked through its extracted terms
- **THEN** the clause with the linked MismatchFlag has a severity in the same band or higher than the one without

### Requirement: Quote-grounded explanation with anti-hallucination gate
The system SHALL construct every RiskAssessment's explanation only from sentences each backed by a verbatim quote from the clause's own clause_text, verified through core.claude_client.quote_is_verbatim. An explanation SHALL fail validation if it contains any sentence whose backing quote is not a verbatim substring of the clause text. On validation failure the system SHALL retry the scoring call exactly once; if the retried explanation also fails validation, the system SHALL force severity to needs_human_review instead of persisting the unverified explanation.

#### Scenario: Fully grounded explanation persists as scored
- **WHEN** every sentence in a generated explanation is backed by a quote that is a verbatim substring of the clause's clause_text
- **THEN** the RiskAssessment is persisted with that explanation and a severity derived from the scoring formula, not forced to needs_human_review

#### Scenario: Unbacked sentence forces human review after one retry
- **WHEN** a generated explanation contains at least one sentence whose backing quote is not a verbatim substring of the clause text, and the retried attempt also contains an unbacked sentence
- **THEN** the persisted RiskAssessment has severity equal to needs_human_review and does not contain the unverified explanation text

### Requirement: Automatic human review inherited from classification
The system SHALL assign severity needs_human_review to a Clause's RiskAssessment without invoking the scoring language model whenever that clause's clause_type is itself needs_human_review or unset.

#### Scenario: Unclassified clause skips scoring entirely
- **WHEN** stage 5 scoring runs for a Clause whose clause_type is needs_human_review or null
- **THEN** the resulting RiskAssessment has severity needs_human_review and no scoring LLM call is issued for that clause

### Requirement: Suggested rewrite scoped to actionable severity
The system SHALL populate suggested_rewrite only for RiskAssessments with severity medium, high, or critical, and SHALL leave it null for severity low or needs_human_review.

#### Scenario: Low-severity or unreviewed clause has no rewrite
- **WHEN** a RiskAssessment is created with severity low or needs_human_review
- **THEN** its suggested_rewrite is null

#### Scenario: Actionable clause includes a rewrite
- **WHEN** a RiskAssessment is created with severity medium, high, or critical from a successful, non-forced scoring pass
- **THEN** its suggested_rewrite is a non-empty string

### Requirement: Mismatch linkage recorded on the assessment
The system SHALL populate linked_mismatch_flag_ids with the ids of every MismatchFlag that references any ExtractedTerm belonging to the assessed clause, evaluated at scoring time.

#### Scenario: Linked ids match the clause's mismatches exactly
- **WHEN** a clause has two ExtractedTerm rows and one MismatchFlag references each
- **THEN** the clause's RiskAssessment.linked_mismatch_flag_ids contains both MismatchFlag ids and no others
