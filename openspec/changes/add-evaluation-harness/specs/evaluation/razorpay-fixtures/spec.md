## Purpose

Provides a fixed, versioned matrix of paired contract-clause and Razorpay test-mode platform-data scenarios so stage 4's mismatch detection can be measured against known-correct verdicts, including cases where the correct behavior is to decline rather than guess.

## ADDED Requirements

### Requirement: Minimum fixture matrix size and mismatch-type coverage
The system SHALL maintain at least 10 paired (contract clause, Razorpay test-mode payout-history-or-subscription-config) fixture scenarios, and every value of `MismatchFlag.mismatch_type` SHALL be covered by at least one scenario in the matrix.

#### Scenario: Every mismatch type is covered
- **WHEN** the fixture matrix is loaded
- **THEN** every `mismatch_type` value that `MismatchFlag` defines appears in at least one fixture scenario

#### Scenario: Minimum matrix size
- **WHEN** the fixture matrix is loaded
- **THEN** it contains at least 10 scenarios

### Requirement: True-negative control scenario
The fixture matrix SHALL include at least one true-negative control scenario in which a fair contract clause's Razorpay test-mode data matches its stated terms exactly, with an expected outcome of no mismatch.

#### Scenario: Control produces no flag
- **WHEN** the true-negative control scenario is run through stage 4
- **THEN** the expected outcome is that no `MismatchFlag` is raised for that clause

### Requirement: Deliberately unverifiable scenario
The fixture matrix SHALL include at least one scenario in which a contract term has no corresponding Razorpay field to check it against, with an expected outcome that the system declines to produce a verdict rather than fabricating platform evidence.

#### Scenario: Unverifiable term declines rather than fabricates
- **WHEN** the unverifiable-term scenario is run through stage 4
- **THEN** the expected outcome is that the term is recorded as unverifiable, and no `MismatchFlag` citing fabricated or absent platform evidence is produced for it

### Requirement: Fixture matrix is versioned and immutable per version
The fixture matrix SHALL carry a version identifier, and an existing version's scenarios and expected verdicts SHALL NOT change after that version is committed — any correction or addition SHALL be published as a new fixture version.

#### Scenario: EvalRun records the fixture version used
- **WHEN** an `EvalRun` scores `MismatchFlag` correctness against the fixture matrix
- **THEN** the fixture version used for that run is recorded on the `EvalRun`

### Requirement: Fixtures are test-mode only
Every fixture scenario's Razorpay data SHALL originate from Razorpay test-mode resources only, and loading or running the fixture matrix SHALL NOT issue any call — read or write — against a live/production Razorpay resource.

#### Scenario: No live-resource calls during fixture evaluation
- **WHEN** fixture scenarios are loaded and run through stage 4 for evaluation
- **THEN** every Razorpay API call made in the process targets test-mode resources, and no call is made against a live/production account, consistent with the project's guardrail confining writes and live-account access to production paths only
