## Purpose

Cross-checks contract-extracted payment terms against real Razorpay Subscription and UPI Autopay Token configuration fields for engagements paid via Subscriptions, using an exact field diff rather than a tolerance band since these fields are configured values, not empirically observed ones.

## ADDED Requirements

### Requirement: Subscription and token fields fetched for diffing
The system SHALL fetch, for a Contract with razorpay_reference_type=subscription, the Subscription's period, interval, item.amount, and total_count fields, and the associated Token's max_amount and expire_at fields, via read-only GET calls, and persist each as a PlatformRecord.

#### Scenario: Subscription and token fields retrieved and persisted
- **WHEN** a Contract has razorpay_reference_type=subscription and a razorpay_reference_id set
- **THEN** the system fetches period, interval, item.amount, and total_count from the Subscription and max_amount and expire_at from the associated Token, and persists each fetched resource as a PlatformRecord with its raw payload

### Requirement: Exact field diff with no tolerance band
The system SHALL compare each fetched Subscription or Token field directly and exactly against the corresponding contract-extracted term value, without applying any tolerance percentage or time-window allowance.

#### Scenario: item.amount differs from the contract-stated amount by any margin
- **WHEN** the Subscription's item.amount differs from an ExtractedTerm's structured amount value by any nonzero amount
- **THEN** an amount_mismatch MismatchFlag is created; no tolerance threshold suppresses the flag

#### Scenario: Fields match exactly
- **WHEN** every fetched Subscription and Token field matches its corresponding ExtractedTerm value exactly
- **THEN** no MismatchFlag is created for those fields

### Requirement: Trigger condition unverifiable for non-diffable terms
The system SHALL flag trigger_condition_unverifiable when a contract-extracted term has no corresponding independently GET-able Subscription or Token field to diff against.

#### Scenario: Milestone-based term has no subscription field equivalent
- **WHEN** an ExtractedTerm of term_type milestone_trigger cannot be mapped to any of period, interval, item.amount, total_count, max_amount, or expire_at
- **THEN** a MismatchFlag of type trigger_condition_unverifiable is created, referencing the ExtractedTerm, with platform_record null

### Requirement: Secondary path restricted to subscription-referenced contracts
The system SHALL run the subscription cross-check only for Contracts whose razorpay_reference_type is subscription, and SHALL NOT issue Subscription or Token GET calls, nor create subscription-path MismatchFlags, for Contracts whose razorpay_reference_type is payout.

#### Scenario: Payout-referenced contract skips the subscription cross-check
- **WHEN** a Contract's razorpay_reference_type is payout
- **THEN** no Subscription or Token GET calls are issued for that Contract and no subscription-path MismatchFlags are created for it
