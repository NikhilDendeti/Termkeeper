## Context

See proposal.md for motivation. Phase 1 (add-django-foundation) delivered the `contracts` app (Contract, Clause), the `pipeline` app (ExtractedTerm, AuditLogEntry, and stages 1-3: segment_contract, classify_clause, extract_terms, orchestrated by run_pipeline(*, contract, from_stage=1)), and `core.claude_client` (get_structured_completion, quote_is_verbatim). Phase 1's stages persist their output before the next stage runs — there is no in-memory handoff of Python objects between stage functions; each stage reads what the previous stage wrote to the database. Stage 4, added here, must follow the same rule: it reads persisted ExtractedTerm rows via a selector, not via an argument passed in-process from stage 3.

This phase adds the first outbound integration to a real third-party API (Razorpay). RazorpayX exposes Payout history via GET but has no queryable payout *schedule* configuration endpoint — schedule/cadence is only visible on the dashboard, never via API. That absence is the reason this product's differentiator is an empirical, history-derived comparison rather than a config-to-config diff, for the primary (Payouts) path. The secondary (Subscriptions) path is a true config-to-config diff, because Subscription and Token fields are independently GET-able configured values.

## Goals / Non-Goals

**Goals**
- Reliable, tolerance-configurable cadence/amount cross-check for payout-referenced Contracts, computed from real Payout history.
- Exact-field diff cross-check for subscription-referenced Contracts.
- Every mismatch persisted with a complete, independently queryable evidence trail (ExtractedTerm + PlatformRecord or explicit absence).
- Zero write (POST/PUT/PATCH/DELETE) calls against live Razorpay account data anywhere in the code path `detect_mismatches` can reach.

**Non-Goals**
- Risk scoring, severity weighting, or ranking of mismatches — phase 3 (add-risk-scoring-report).
- Any report rendering, aggregate report endpoint, or UI — phase 3 and phase 5.
- Synthetic dataset generation, evaluation harness, or precision/recall scoring — phase 4 (add-evaluation-harness).
- Consuming Razorpay webhooks or any real-time event stream — out of scope for this product entirely; all platform evidence in this phase is pulled via on-demand GET during pipeline stage 4.

## Decisions

**New app: `razorpay_integration`**

Models (fields/constraints/simple validation only, per HackSoft convention — no business logic on the model):

```
PlatformRecord
  id: UUID (pk)
  contract: FK(contracts.Contract)
  record_type: enum[payout, subscription, token]
  razorpay_id: str
  payload: JSONField            # raw API response, verbatim
  razorpay_created_at: datetime
  fetched_at: datetime          # auto_now_add

MismatchFlag
  id: UUID (pk)
  extracted_term: FK(pipeline.ExtractedTerm)
  platform_record: FK(PlatformRecord, null=True)
  mismatch_type: enum[cadence_mismatch, amount_mismatch, missing_platform_evidence, trigger_condition_unverifiable]
  expected_value: JSONField
  actual_value: JSONField
  description: TextField
  created_at: datetime          # auto_now_add
```

`services.py` (follows convention, no deviation — plain functions, one per use case, keyword-only args):

```
fetch_payout_history(*, contract: Contract) -> list[PlatformRecord]
fetch_subscription_config(*, contract: Contract) -> list[PlatformRecord]
detect_mismatches(*, contract: Contract) -> list[MismatchFlag]
```

`selectors.py` (follows convention, no deviation):

```
get_platform_records_for_contract(*, contract: Contract, record_type: str | None = None) -> QuerySet[PlatformRecord]
list_mismatch_flags_for_contract(*, contract: Contract) -> QuerySet[MismatchFlag]
get_latest_payout_records(*, contract: Contract, minimum: int = 2) -> QuerySet[PlatformRecord]
```

No DRF serializers or views are added in this phase — phase 3 exposes report endpoints that will read MismatchFlag via these selectors; this phase is pipeline-internal.

**`razorpay_integration/client.py` — read-only connector.** A `RazorpayConnector` class wraps the `razorpay` Python SDK with a raw-`requests` fallback, exposing exactly three methods used by the production path: `fetch_payouts(fund_account_id)`, `fetch_subscription(subscription_id)`, `fetch_token(token_id)`. None of these methods, nor any other code reachable from `detect_mismatches`, issues a POST/PUT/PATCH/DELETE request. This is enforced by a test that statically scans `client.py` for any SDK/requests call using a non-GET verb and fails if one is found in a function reachable from the production path.

**`razorpay_integration/fixtures.py` — the only place writes happen.** All test-mode seeding (creating Contacts, Fund Accounts, Payouts, Subscriptions, Tokens for demo/dev data) lives here, in a module `services.py` and `client.py` never import. A dedicated test asserts `fixtures` is not present in the transitive import graph of `detect_mismatches`. `fixtures.py` is invoked only from management commands or test setup, explicitly, never from the pipeline.

**Extending `run_pipeline` without a circular import.** `razorpay_integration` depends on `pipeline` (it reads ExtractedTerm via a pipeline selector) and on `contracts`. But `pipeline.services.run_pipeline` must now *call* `razorpay_integration.services.detect_mismatches` after stage 3. A module-level `import razorpay_integration.services` at the top of `pipeline/services.py` would create a circular import (`razorpay_integration.services` imports `pipeline.selectors`, and `pipeline.services` would import `razorpay_integration.services`). Decision: `run_pipeline` performs a **function-local import** of `razorpay_integration.services` inside its own body, not at module scope. By the time `run_pipeline` is actually called, both modules have finished loading, so the local import resolves cleanly. This is a pragmatic, explicitly-scoped exception documented here rather than a silent workaround.
  - *Alternative considered — app-registry/signal dispatch* (razorpay_integration registers a stage-4 handler with pipeline at `AppConfig.ready()` time): rejected as unnecessary indirection for a 5-phase hackathon build; revisit only if a third app needs to plug into `run_pipeline` the same way.
  - *Alternative considered — moving run_pipeline itself into a new top-level orchestration module with no owning app*: rejected, since it would require phase 1's already-validated `pipeline.services.run_pipeline` signature to move, which the project brief explicitly says to depend on verbatim, not restructure.
- `detect_mismatches` still fetches its own inputs via `pipeline.selectors.list_extracted_terms_for_clause` (per-clause) or a Contract-wide iteration over `contracts.selectors.list_clauses_for_contract`, and writes AuditLogEntry(stage=4, ...) rows itself — `run_pipeline` passes only `contract`, never pre-fetched ExtractedTerm objects, preserving the no-in-memory-handoff rule.

**Tolerance configuration.** `CADENCE_MISMATCH_TOLERANCE_RATIO` (fraction of the contract-stated interval, e.g. 0.2 = 20%) and `AMOUNT_MISMATCH_TOLERANCE_PCT` (fraction of the contract-stated amount, e.g. 0.05 = 5%) are read from Django settings with defaults, overridable per environment — not hardcoded in `services.py`. The subscription path applies neither setting: its diff is exact, per the subscription-crosscheck spec.

**PlatformRecord stores the raw payload.** Mirrors phase 1's `AuditLogEntry.llm_response_raw` pattern: the full API response JSON is kept verbatim in `payload`, independent of whatever fields the comparison logic actually reads, so a future stage or a human reviewer can audit exactly what Razorpay returned.

**Quote verification reuses phase 1's primitive as-is.** `core.claude_client.quote_is_verbatim(source, quote)` is called on both the expected-value quote (source = the ExtractedTerm's value_raw) and the actual-value quote (source = the relevant PlatformRecord payload, stringified) before a description is persisted. See the "Unverifiable quote falls back to a deterministic description" scenario in the mismatch-flagging spec for the failure path.

**Token resolution for the subscription path.** A Contract's `razorpay_reference_id` is the Subscription id when `razorpay_reference_type=subscription` (mirroring how it is the fund_account_id when `razorpay_reference_type=payout`, per phase 1's Contract fields — no new Contract field is introduced). The active UPI Autopay Token for a Subscription is resolved via a second GET keyed off the Subscription's linked payment-method/customer reference, then filtered to the token with the latest `razorpay_created_at` that is not in a cancelled state (see Risks below for why cancellation status is never trusted from a mutation response).

## Risks / Trade-offs

- [Risk] India-only IFSC/account-number validation could block demo fund-account setup entirely. -> Mitigation: `fixtures.py` seeds only test-mode fund accounts using Razorpay's documented dummy IFSC/account values; the production cross-check path never creates a fund account, it only reads the fund_account_id already stored on `contract.razorpay_reference_id`.
- [Risk] UPI Autopay tokens cannot be PATCHed — a renegotiated mandate must be modeled as cancel+recreate, which can leave two Token PlatformRecords under one logical mandate. -> Mitigation: every fetched Token is persisted as its own PlatformRecord (never overwritten); the subscription cross-check selects the token with the latest `razorpay_created_at` that is not cancelled as the one to diff against, while older cancelled tokens remain in PlatformRecord history for audit.
- [Risk] UPI test-mode cancellation always reports HTTP success regardless of real outcome. -> Mitigation: the connector never treats a cancellation response body as authoritative; any token-state-dependent comparison re-fetches the Token via GET and trusts only the re-fetched `status` field.
- [Risk] Card tokens expire after 3 days in test mode, which can make demo fixtures silently stale between build sessions. -> Mitigation: `fixtures.py`'s seeding path checks token freshness before each demo run and re-seeds if `expire_at` has passed; the production cross-check path treats an already-expired token as a legitimate GET result and surfaces it as-is in the diff rather than erroring.
- [Risk] Circular import between `pipeline` (owns run_pipeline) and `razorpay_integration` (depends on pipeline). -> Mitigation: function-local import inside `run_pipeline`, verified by a test that imports `pipeline.services` in isolation with `razorpay_integration` not pre-imported.
- [Risk] Median-based cadence can still be skewed by a single very early or very late payout in a short history. -> Mitigation: median (not mean) was chosen specifically for outlier resistance; the computation is fixed by the payout-history-crosscheck spec, not per-contract configurable, in this phase.

## Migration Plan

- Add `razorpay_integration` to `INSTALLED_APPS`.
- Generate and hand-review one migration creating `PlatformRecord` and `MismatchFlag` (FKs into `contracts.Contract` and `pipeline.ExtractedTerm`); net-new tables, no data migration required.
- Add settings `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` (env-var-backed, test-mode keys for development), `CADENCE_MISMATCH_TOLERANCE_RATIO`, `AMOUNT_MISMATCH_TOLERANCE_PCT`.
- Gate the stage-4 call behind a settings flag (e.g. `ENABLE_STAGE_4`, defaulting True) so `run_pipeline` degrades gracefully to stages 1-3 only if this app needs to be disabled without a code rollback.
- Rollback: flip `ENABLE_STAGE_4` off (or remove `razorpay_integration` from `INSTALLED_APPS`) and reverse the migration (drop `MismatchFlag` before `PlatformRecord`, respecting the FK). No phase-1 model or migration is touched by rollback.
- No backward-incompatible change to any phase-1 model: `AuditLogEntry.stage` simply gains observed value 4, which is compatible by construction since the field is an unconstrained int.
