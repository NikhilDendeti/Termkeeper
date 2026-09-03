## Purpose

Cross-checks contract-derived payout frequency and amount terms against real RazorpayX Payout history, treating empirical cadence and amount derived from actual Payout timestamps as the honest ground truth, since RazorpayX exposes no queryable payout schedule configuration via API — only via dashboard.

## ADDED Requirements

### Requirement: Empirical cadence derivation from payout history
The system SHALL derive an empirical payout cadence for a Contract by computing the median of the time deltas between consecutive created_at timestamps of that Contract's fetched Payout records, whenever at least 2 Payout records exist for the Contract's configured fund_account_id.

#### Scenario: Cadence computed from three payouts
- **WHEN** at least 2 Payout records are fetched for the Contract's fund_account_id
- **THEN** an empirical cadence value is computed as the median of the consecutive created_at deltas across the fetched Payout records, ordered by created_at

### Requirement: Empirical amount derivation from payout history
The system SHALL derive an empirical payout amount for a Contract by computing the median of the amounts of that Contract's fetched Payout records, whenever at least 2 Payout records exist.

#### Scenario: Amount computed from multiple payouts
- **WHEN** at least 2 Payout records are fetched for the Contract's fund_account_id
- **THEN** an empirical amount value is computed as the median of the fetched Payout amounts

### Requirement: Cadence mismatch detection against a configured tolerance
The system SHALL flag a cadence_mismatch when the empirical cadence derived from Payout history differs from the interval stated in a payout_frequency ExtractedTerm's value_structured by more than a configured tolerance.

#### Scenario: Contract states monthly but payouts occur weekly
- **WHEN** a payout_frequency ExtractedTerm states an interval and the empirical cadence computed from Payout history deviates from that interval by more than the configured tolerance
- **THEN** a MismatchFlag of type cadence_mismatch is created, referencing the ExtractedTerm and the PlatformRecord(s) used to compute the empirical cadence

#### Scenario: Empirical cadence within tolerance produces no flag
- **WHEN** a payout_frequency ExtractedTerm states an interval and the empirical cadence computed from Payout history deviates from that interval by no more than the configured tolerance
- **THEN** no cadence_mismatch MismatchFlag is created for that ExtractedTerm

### Requirement: Amount mismatch detection against a configured tolerance
The system SHALL flag an amount_mismatch when the empirical amount derived from Payout history differs from the amount stated in an ExtractedTerm's value_structured by more than a configured percentage tolerance.

#### Scenario: Contract-stated amount differs from empirical payout amount beyond tolerance
- **WHEN** an ExtractedTerm states a payout amount and the empirical amount computed from Payout history deviates from that stated amount by more than the configured percentage tolerance
- **THEN** a MismatchFlag of type amount_mismatch is created, referencing the ExtractedTerm and the PlatformRecord(s) used to compute the empirical amount

### Requirement: Missing platform evidence when insufficient payout history exists
The system SHALL flag missing_platform_evidence, rather than computing a cadence or amount mismatch, whenever fewer than 2 Payout records exist for the Contract's configured fund_account_id.

#### Scenario: Zero or one payout exists
- **WHEN** fewer than 2 Payout records are returned for the Contract's razorpay_reference_id
- **THEN** a MismatchFlag of type missing_platform_evidence is created and no cadence_mismatch or amount_mismatch is computed for that Contract's payout_frequency ExtractedTerms

### Requirement: No claim of a payout schedule configuration
The system SHALL NOT represent, in any persisted MismatchFlag description or other output, that a Razorpay-side payout schedule configuration was retrieved, checked, or exists, since RazorpayX exposes no such queryable configuration via API.

#### Scenario: Description characterizes the comparison as history-based
- **WHEN** a payout-history-derived MismatchFlag description (cadence_mismatch, amount_mismatch, or missing_platform_evidence) is generated
- **THEN** the description characterizes the platform-side evidence as observed or empirical Payout history, and does not describe it as a "payout schedule," "schedule configuration," or any equivalent phrase implying a queryable schedule setting exists on the Payouts side
