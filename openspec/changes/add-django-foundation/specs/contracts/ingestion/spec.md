## Purpose

Lets a caller submit a contract's raw text and engagement metadata so the pipeline has a persisted, addressable Contract to run against.

## ADDED Requirements

### Requirement: Contract creation from raw text
The system SHALL accept a contract's raw text, an engagement identifier, and a Razorpay reference (type and id) and persist them as a Contract record with a unique identifier.

#### Scenario: Valid contract submitted
- **WHEN** a caller submits non-empty contract text with an engagement_id and a razorpay_reference_type of "payout" or "subscription"
- **THEN** the system creates a Contract record and returns its identifier

#### Scenario: Missing razorpay reference rejected
- **WHEN** a caller submits contract text without a razorpay_reference_type or razorpay_reference_id
- **THEN** the system rejects the submission with a validation error identifying the missing field

### Requirement: Engagement traceability
Every Contract SHALL retain the engagement_id and Razorpay reference it was created with, unmodified for the lifetime of the record, so later phases can resolve which live Razorpay resource to cross-check against.

#### Scenario: Reference resolvable after creation
- **WHEN** a Contract has been created
- **THEN** its razorpay_reference_type and razorpay_reference_id are retrievable and unchanged from what was submitted at creation
