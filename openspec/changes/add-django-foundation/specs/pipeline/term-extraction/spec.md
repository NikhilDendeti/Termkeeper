## Purpose

Pulls the concrete, stated payment terms out of the clauses that carry them, so later phases have structured values to cross-check against a live payment rail.

## ADDED Requirements

### Requirement: Extraction scoped to payment-bearing clause types
The system SHALL attempt term extraction only for clauses classified as payment_schedule, penalty_late_fee, or auto_renewal; clauses of any other type SHALL NOT produce an ExtractedTerm.

#### Scenario: Non-payment clause skips extraction
- **WHEN** a clause is classified as termination, dispute_resolution, indemnity, or other
- **THEN** no ExtractedTerm is created for that clause

### Requirement: Only stated values are extracted
The system SHALL extract only values explicitly stated in the clause text and SHALL leave a term's numeric fields unset when the clause states the term qualitatively rather than numerically.

#### Scenario: Qualitative term leaves numeric fields unset
- **WHEN** a clause states a payment condition in qualitative language, such as "within a reasonable time", with no explicit number
- **THEN** the resulting ExtractedTerm has its numeric fields unset rather than a guessed value

### Requirement: Low-confidence or unparseable extraction escalated
The system SHALL mark an ExtractedTerm needs_human_review when a required field cannot be parsed from the clause, or when extraction confidence falls below the configured threshold.

#### Scenario: Formula-based term flagged
- **WHEN** a clause states a payment term as a formula the term schema cannot represent numerically, such as a compounding percentage
- **THEN** the resulting ExtractedTerm is marked needs_human_review and its raw text is preserved

### Requirement: Extracted term traceable to its clause
Every ExtractedTerm SHALL retain a reference to the clause it was extracted from and the verbatim span of text the value was read from.

#### Scenario: Term evidence retrievable
- **WHEN** an ExtractedTerm is retrieved
- **THEN** the clause it belongs to and the verbatim source text for its value are both retrievable
