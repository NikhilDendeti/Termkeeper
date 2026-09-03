## Purpose

Splits a Contract's raw text into individually addressable, verbatim clauses so every later pipeline stage and every risk flag can be traced back to an exact span of the original contract.

## ADDED Requirements

### Requirement: Verbatim clause extraction
The system SHALL split a Contract's raw text into an ordered sequence of clauses, each reproduced character-for-character from the source text.

#### Scenario: Clause text matches source exactly
- **WHEN** segmentation completes for a Contract
- **THEN** every resulting clause's text is found verbatim within the Contract's raw_text

### Requirement: Multi-topic clauses stay whole
The system SHALL NOT split a single clause, including its sub-bullets, across multiple clause records; classifying a multi-topic clause is a later stage's responsibility.

#### Scenario: Clause with sub-bullets segmented as one unit
- **WHEN** a contract clause contains multiple sub-bullets under one heading
- **THEN** segmentation produces exactly one clause record spanning the whole unit, not one record per sub-bullet

### Requirement: Segmentation failure is escalated, not silently repaired
The system SHALL flag a Contract for human review, rather than guess, when a proposed clause cannot be located verbatim in the source text after one retry.

#### Scenario: Non-verbatim output after retry
- **WHEN** a proposed clause's text cannot be found in the Contract's raw_text on a second attempt
- **THEN** the system marks the Contract needs_human_review and does not persist an unverifiable clause

### Requirement: Clause ordering preserved
Each clause SHALL retain a sequence_index reflecting its position in the source contract.

#### Scenario: Clauses retrievable in source order
- **WHEN** clauses for a Contract are retrieved
- **THEN** they are returned in the same order they appear in the Contract's raw_text
