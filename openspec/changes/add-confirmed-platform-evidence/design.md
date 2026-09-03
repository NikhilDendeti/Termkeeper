## Context

`reporting.selectors.get_contract_reasoning_chain` already joins `contracts`, `pipeline`, and `risk_scoring`'s own selectors per clause (see its module docstring). `razorpay_integration.selectors.get_platform_records_for_contract(*, contract, record_type=None)` already exists and returns a Contract's `PlatformRecord`s, optionally filtered by `record_type`. `Contract.razorpay_reference_type` is already `"payout"` or `"subscription"` (`RazorpayReferenceType`), the same field `razorpay_integration.services.detect_mismatches` branches on to pick its cross-check path. This change reuses both without modification.

## Goals / Non-Goals

**Goals:** make "checked, matched" visually and structurally distinct from "never checked," using only existing selectors — no new persistence.

**Non-Goals:** no change to `detect_mismatches`'s persistence behavior; no per-term matching logic (e.g. this does not try to prove *which* specific platform record "matches" a specific term — it surfaces the contract's relevant platform records as supporting context once the absence of a `MismatchFlag` establishes nothing was found to contradict them, consistent with how `detect_mismatches` itself treats silence as agreement).

## Decisions

**`reporting/selectors.py`: extend `ClauseReasoningChain` with `verified_platform_records: list[PlatformRecord]`.** Computed in `get_contract_reasoning_chain`'s existing per-clause loop: if `extracted_terms` is non-empty and `mismatch_flags` is empty, call `razorpay_integration.selectors.get_platform_records_for_contract(contract=contract, record_type=...)` — `PlatformRecordType.PAYOUT` when `contract.razorpay_reference_type == RazorpayReferenceType.PAYOUT`, else fetch both `SUBSCRIPTION` and `TOKEN` records (two calls, concatenated) — and assign the result (or an empty list if none exist) to `verified_platform_records`. Otherwise `verified_platform_records = []`. This one extra query per qualifying clause is acceptable at this project's scale (tens of clauses per contract), consistent with `get_contract_reasoning_chain`'s existing per-clause-selector-call pattern.

**`reporting/serializers.py`: add `PlatformRecordSerializer`** (`id`, `record_type`, `razorpay_id`, `payload`, `razorpay_created_at`) and add `verified_platform_records = PlatformRecordSerializer(many=True)` to `ClauseReasoningChainSerializer`.

**`report_ui` template**: in the reasoning-chain clause partial, add a branch — mismatch_flags non-empty → existing mismatch rendering (unchanged); else verified_platform_records non-empty → new "Confirmed — matches platform data" block listing each record's `record_type`, `razorpay_id`, and a short summary of its payload (amount/period as applicable); else → existing "No platform evidence available" (unchanged).

**Frontend**: `frontend/src/api/types.ts` gains a `PlatformRecord` interface and `ClauseReasoningChain.verified_platform_records: PlatformRecord[]`. `ContractDetailPage.tsx`'s reasoning-chain section gains the same three-way branch, styled distinctly from the existing mismatch state (e.g. a green "Confirmed" treatment, not reusing the mismatch's warning color) — follows convention, no deviation from the existing component structure.

## Risks / Trade-offs

- **[Risk]** Confirmed evidence is inferred (absence of a mismatch), not a persisted fact — if `detect_mismatches` is ever re-run with different tolerances, a previously "confirmed" clause could later mismatch without this field itself changing until the next reasoning-chain read. → **Mitigation**: acceptable — `get_contract_reasoning_chain` is computed fresh on every call (no caching), so it always reflects the current `MismatchFlag` state at read time; there is no staleness beyond normal read-after-write consistency.
- **[Risk]** For a subscription-referenced contract, "relevant platform records" fetches both SUBSCRIPTION and TOKEN types even if only one is meaningful for a given term. → **Mitigation**: accepted for simplicity; both are legitimate configured-mandate evidence per `add-razorpay-crosscheck`'s design, and showing both is more informative, not less honest.

## Migration Plan

No models, no migrations. Rollout: (1) backend selector + serializer change, verified with tests before either UI touches it; (2) `report_ui` and the React frontend updated in parallel once the backend's field shape is stable — neither depends on the other.
