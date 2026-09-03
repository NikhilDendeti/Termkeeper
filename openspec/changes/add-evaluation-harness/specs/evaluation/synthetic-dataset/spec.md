## Purpose

Generates a labeled synthetic freelance/vendor contract dataset that exercises the pipeline across engagement types, domains, clause severity, and phrasing style, with numeric ground truth fixed before any contract prose is written, so the scoring harness has known-correct answers to score against.

## ADDED Requirements

### Requirement: Five-axis dataset coverage
The system SHALL generate each synthetic contract from five independent axes: `engagement_type` (fixed-fee, milestone, retainer), `domain` (design, dev, content, consulting), `clause_severity_profile` (fair, mildly-one-sided, deliberately-exploitative) assigned per clause rather than uniformly per contract, `phrasing_style` (plain, legalese, deliberately-vague), and `razorpay_reference_type` (payout, subscription). Across the full generated dataset, every value of every axis SHALL appear in at least one contract.

#### Scenario: Severity varies within one contract
- **WHEN** a contract is generated with an overall `clause_severity_profile` mix
- **THEN** individual clauses in that contract carry independently assigned severities, such that a contract whose profile is predominantly fair can still contain at least one deliberately-exploitative clause

#### Scenario: Full axis coverage across the dataset
- **WHEN** the full dataset for a `dataset_version` is generated
- **THEN** every defined value of `engagement_type`, `domain`, `clause_severity_profile`, `phrasing_style`, and `razorpay_reference_type` appears in at least one contract in that dataset

### Requirement: Ground truth generated before prose
The system SHALL generate concrete numeric ground truth values (`amount`, `cadence_days`, `notice_period_days`, `penalty_pct`) for a clause before generating the contract prose that expresses that clause, and SHALL NOT derive a ground truth value by parsing or reverse-engineering already-generated contract text.

#### Scenario: Ground truth precedes phrasing
- **WHEN** a synthetic contract's payment-bearing clause is generated
- **THEN** its numeric ground truth values exist prior to, and independently of, the model call that phrases that clause's prose

#### Scenario: Ground truth is never back-derived from prose
- **WHEN** a synthetic clause's ground truth values are inspected
- **THEN** none of them were produced by extracting or parsing the clause's own generated text — they trace back to the pre-phrasing generation parameters

### Requirement: Per-clause human labeling rubric
Every generated clause SHALL be labeled with `clause_type`, `risky` (boolean), `severity` (an integer 1 through 5), a one-sentence rationale naming the specific asymmetry mechanism the clause creates, and `needs_human_review` (boolean, set true for deliberately ambiguous clauses).

#### Scenario: Label completeness
- **WHEN** a clause is labeled per the rubric
- **THEN** `clause_type`, `risky`, `severity`, `rationale`, and `needs_human_review` are all present, `severity` is an integer between 1 and 5 inclusive, and `rationale` is a non-empty statement naming an asymmetry mechanism

### Requirement: Per-contract risk tier with a floor rule
Every generated contract SHALL be labeled with an `overall_risk_tier`, and this tier SHALL be forced to `critical` whenever the contract contains two or more clauses labeled with `severity` 4 or higher, regardless of whether any single clause reaches `severity` 5.

#### Scenario: Floor rule forces critical tier
- **WHEN** a contract has two or more clauses labeled with `severity` 4 or higher
- **THEN** the contract's `overall_risk_tier` is `critical`, even if no individual clause in that contract is labeled `severity` 5

### Requirement: Dataset size bounds
The system SHALL generate between 30 and 50 synthetic contracts, inclusive, per dataset version.

#### Scenario: Dataset size within bounds
- **WHEN** a `dataset_version` is generated
- **THEN** the number of contracts produced for that version is between 30 and 50 inclusive
