## Purpose

Cross-checks contract-derived flat-amount commission and referral terms against real Razorpay Route Transfer history, treating an empirical amount derived from actual Transfer records as the honest ground truth — the same empirical, history-based pattern the payout-history-crosscheck capability already established — since a Route Transfer carries only a fixed amount, never a percentage-of-total or a schedule, so this path is scoped to flat-amount splits only.

## ADDED Requirements

### Requirement: Third path selected by transfer-referenced contracts
The system SHALL run the Route Transfer cross-check only for Contracts whose razorpay_reference_type is transfer, and SHALL NOT issue Transfer GET calls, nor create route-path MismatchFlags, for Contracts whose razorpay_reference_type is payout or subscription.

#### Scenario: Transfer-referenced contract runs the route cross-check
- **WHEN** a Contract has razorpay_reference_type=transfer and a razorpay_reference_id set
- **THEN** the system fetches that Contract's Route Transfer history and runs the route cross-check against it

#### Scenario: Payout- or subscription-referenced contract skips the route cross-check
- **WHEN** a Contract's razorpay_reference_type is payout or subscription
- **THEN** no Transfer GET calls are issued for that Contract and no route-path MismatchFlags are created for it

### Requirement: Transfer records fetched via read-only GET calls
The system SHALL fetch a Contract's Route Transfer history via read-only GET calls only, and persist each fetched Transfer as a PlatformRecord, mirroring the existing production-path guardrail that no cross-check code path ever issues a POST, PUT, PATCH, or DELETE against live Razorpay data.

#### Scenario: Transfer history retrieved and persisted
- **WHEN** a Contract has razorpay_reference_type=transfer and a razorpay_reference_id set
- **THEN** the system issues only GET requests to fetch that Contract's Transfer history, and persists each fetched Transfer as a PlatformRecord with its raw payload

### Requirement: Empirical amount derivation from Route Transfer history
The system SHALL derive an empirical Route split amount for a Contract by computing the median of the amounts of that Contract's fetched Transfer records, whenever at least 2 Transfer records exist.

#### Scenario: Amount computed from multiple Transfers
- **WHEN** at least 2 Transfer records are fetched for the Contract's razorpay_reference_id
- **THEN** an empirical amount value is computed as the median of the fetched Transfer amounts

### Requirement: Amount mismatch detection against a configured tolerance
The system SHALL flag an amount_mismatch when the empirical amount derived from Route Transfer history differs from the flat amount stated in a payout_frequency ExtractedTerm's value_structured by more than the configured amount-mismatch tolerance.

#### Scenario: Contract-stated flat commission differs from empirical Transfer amount beyond tolerance
- **WHEN** a payout_frequency ExtractedTerm states a flat amount and the empirical amount computed from Route Transfer history deviates from that stated amount by more than the configured tolerance
- **THEN** a MismatchFlag of type amount_mismatch is created, referencing the ExtractedTerm and the PlatformRecord(s) used to compute the empirical amount

#### Scenario: Empirical amount within tolerance produces no flag
- **WHEN** a payout_frequency ExtractedTerm states a flat amount and the empirical amount computed from Route Transfer history deviates from that stated amount by no more than the configured tolerance
- **THEN** no amount_mismatch MismatchFlag is created for that ExtractedTerm

### Requirement: Missing platform evidence when insufficient Transfer history exists
The system SHALL flag missing_platform_evidence, rather than computing an amount mismatch, whenever fewer than 2 Transfer records exist for the Contract's razorpay_reference_id.

#### Scenario: Zero or one Transfer exists
- **WHEN** fewer than 2 Transfer records are returned for the Contract's razorpay_reference_id
- **THEN** a MismatchFlag of type missing_platform_evidence is created and no amount_mismatch is computed for that Contract's flat-amount payout_frequency ExtractedTerms

### Requirement: Percentage-based splits are out of scope for Route cross-checking
The system SHALL NOT compare a percentage-denominated payout_frequency term's stated value against a Transfer's amount field, and SHALL instead flag such a term trigger_condition_unverifiable, since Razorpay's Transfer object exposes no percentage-of-total field to diff against and computing one would require fetching the parent Payment object, which this capability does not do.

#### Scenario: Contract states a percentage-of-revenue commission
- **WHEN** a payout_frequency ExtractedTerm's value_structured states a percentage-denominated value rather than a flat currency amount
- **THEN** a MismatchFlag of type trigger_condition_unverifiable is created for that term, referencing the ExtractedTerm, with platform_record null, and no amount_mismatch or missing_platform_evidence flag is computed against Transfer amount for that term

#### Scenario: Contract states a time-based cadence with no flat amount
- **WHEN** a payout_frequency ExtractedTerm states a time interval rather than a flat currency amount
- **THEN** a MismatchFlag of type trigger_condition_unverifiable is created for that term, referencing the ExtractedTerm, with platform_record null, since a Route Transfer carries no schedule field to diff a cadence against

### Requirement: No claim of a Route split-rule configuration
The system SHALL NOT represent, in any persisted MismatchFlag description or other output, that a Razorpay-side Route split-rule or percentage configuration was retrieved, checked, or exists, since Razorpay stores a split only as the amount on an individual, already-executed Transfer — never as an independently queryable split-rule or percentage object.

#### Scenario: Description characterizes the comparison as history-based
- **WHEN** a route-path MismatchFlag description (amount_mismatch or missing_platform_evidence) is generated
- **THEN** the description characterizes the platform-side evidence as observed or empirical Transfer history, and does not describe it as a "split rule," "split configuration," or any equivalent phrase implying a queryable split-rule setting exists on the Route side

### Requirement: Deterministic mismatch classification precedes any LLM involvement
The system SHALL compute whether a route-path mismatch exists, and its mismatch_type, via deterministic code comparison of extracted-term and Transfer values before any LLM call is made for that comparison; the LLM SHALL NOT be used to decide whether a route-path mismatch exists. This extends the same rule the mismatch-flagging capability already established for the payout and subscription paths — "the system SHALL compute whether a mismatch exists, and its mismatch_type, via deterministic code comparison... before any LLM call is made" — to Route Transfer comparisons.

#### Scenario: Route mismatch decision made without an LLM call
- **WHEN** a Route Transfer amount comparison is evaluated
- **THEN** the mismatch_type and the decision to create a MismatchFlag are determined entirely by deterministic comparison logic, and no core.llm_client call is issued for a comparison that did not deterministically produce a MismatchFlag
