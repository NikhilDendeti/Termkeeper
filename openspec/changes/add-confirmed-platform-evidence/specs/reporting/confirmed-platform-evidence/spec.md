## Purpose

Lets a viewer of the reasoning chain distinguish "this term was checked against real platform data and matched" from "no platform data existed to check against" — closing a real gap where both cases previously rendered identically.

## ADDED Requirements

### Requirement: Confirmed platform evidence shown when a term matches
The system SHALL include, for a clause with at least one extracted term and zero linked mismatch flags, the contract's relevant platform records as confirmed evidence, when such records exist.

#### Scenario: Matching contract shows confirmed evidence
- **WHEN** a clause's extracted term has no linked mismatch flag and the contract has relevant platform records (payout records for a payout-referenced contract, subscription/token records for a subscription-referenced one)
- **THEN** the reasoning chain entry for that clause includes those platform records as confirmed evidence

### Requirement: Absence of platform data is distinct from a confirmed match
The system SHALL NOT populate confirmed platform evidence for a clause whose contract has no relevant platform records at all.

#### Scenario: No platform data ever checked
- **WHEN** a clause's contract has zero platform records of any relevant type (for example, Razorpay cross-check was disabled for that contract)
- **THEN** the reasoning chain entry for that clause has empty confirmed platform evidence, distinct from a clause that was actually checked and matched

### Requirement: A mismatch takes precedence over confirmed evidence
The system SHALL NOT populate confirmed platform evidence for a clause that already has a linked mismatch flag.

#### Scenario: Mismatched clause does not also show confirmed evidence
- **WHEN** a clause's extracted term has a linked mismatch flag
- **THEN** the reasoning chain entry for that clause shows the mismatch, and confirmed platform evidence remains empty for that clause
