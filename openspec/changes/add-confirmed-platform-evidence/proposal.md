## Why

A live check of the actual UI (both `report_ui` and the React `frontend`) found that a clause whose extracted term was checked against real Razorpay data and found to *match* renders identically to a clause with no platform data at all — both show "No platform evidence available." This undersells the tool's own "true negative" story: proving the detector doesn't cry wolf on a fair, matching contract is one of this project's stated evaluation goals (the eval harness's fixture matrix has a dedicated true-negative control for exactly this reason), but the UI currently has no way to show a *confirmed match* distinct from *no evidence checked at all*.

**Non-goals**: this does not change `razorpay_integration.services.detect_mismatches`'s persistence behavior — it still only persists a `MismatchFlag` on an actual deviation, which remains the correct, honest design (inventing a "confirmed match" database row for every non-mismatch would be noise, not signal). This change is read-side only: when assembling the reasoning chain, infer "checked, no mismatch found" from the absence of a `MismatchFlag` alongside the presence of relevant `PlatformRecord` data for the contract, rather than persisting anything new.

## What Changes

- `reporting.selectors.ClauseReasoningChain` gains a `verified_platform_records` field: populated only for a clause that has at least one `ExtractedTerm`, has zero linked `MismatchFlag`s, and whose contract has relevant `PlatformRecord` data (payout records for a payout-referenced contract, subscription/token records for a subscription-referenced one) — otherwise empty, preserving today's "no platform evidence available" case for contracts with no platform data checked at all.
- `reporting.serializers.ClauseReasoningChainSerializer` and the React frontend's `ClauseReasoningChain` type gain the matching field.
- Both UIs (`report_ui` templates and the React `ContractDetailPage`) render a distinct "Confirmed — matches platform data" state when this field is non-empty, visually different from both "flagged mismatch" and "no evidence available."

## Capabilities

### New Capabilities
- `reporting/confirmed-platform-evidence`: the reasoning chain distinguishes "checked against real platform data, no mismatch found" from "no platform data was available to check against."

### Modified Capabilities
(none — no prior change has been archived, nothing under `openspec/specs/` to declare a delta against, per this project's established constraint.)

## Impact

- **Changed**: `reporting/selectors.py`, `reporting/serializers.py`; `report_ui`'s reasoning-chain template; `frontend/src/api/types.ts` and `frontend/src/pages/ContractDetailPage.tsx`.
- **No impact** on `razorpay_integration.services.detect_mismatches` or any pipeline/scoring behavior — purely additive on the read side.
