## Context

See proposal.md for motivation. add-razorpay-crosscheck (already applied) delivered `razorpay_integration`'s `PlatformRecord`/`MismatchFlag` models, its `RazorpayConnector` (GET-only, SDK-primary with a raw-`requests` fallback), its `services.py` cross-check machinery, and `detect_mismatches`'s branch-on-`razorpay_reference_type` orchestration, called unconditionally by `pipeline.services.run_pipeline` after stage 3 via a function-local import, with a stage-4 failure caught and logged rather than allowed to stop the pipeline. This change adds a third branch to that same orchestrator; it does not touch `pipeline.services.run_pipeline` itself.

Razorpay's Route API models a multi-party split as one or more `Transfer` objects, each carrying a destination `account`, a fixed-paise `amount`, a `status` (created/pending/processed/failed/reversed/partially_reversed), and hold fields (`on_hold`, `on_hold_until`). Unlike a Subscription's `item.amount` (a single configured value read once), a Route split has no independently queryable "split-rule" object — every Transfer is a record of one already-executed split, tied to a specific parent payment. That makes the Route path structurally closer to the **payout** path than to the **subscription** path: cadence/amount for Payouts and amount for Route Transfers are both derived empirically, as a median across multiple observed records, rather than read once from a single config object. This is why `_run_route_crosscheck` reuses the payout path's median/tolerance helpers directly rather than the subscription path's exact-diff helpers.

## Goals / Non-Goals

**Goals**
- Empirical, tolerance-configurable amount cross-check for transfer-referenced Contracts, computed from real Route Transfer history, using the exact comparison machinery (`_compute_empirical_amount`, `_evaluate_amount_term`, `AMOUNT_MISMATCH_TOLERANCE_PCT`) the payout path already validated.
- A stated, tested boundary — not silent scope creep — around percentage-denominated and cadence-denominated payout_frequency terms, which this path cannot diff against a Transfer's fields.
- Zero write (POST/PUT/PATCH/DELETE) calls against live Razorpay account data anywhere in the code path `detect_mismatches` can reach, extending the existing guardrail tests to cover the new connector method.

**Non-Goals**
- Percentage-of-revenue split cross-checking. A Transfer's `amount` is always a fixed paise integer; there is no `percentage` field on the Transfer object. Supporting a percentage clause would require a second GET against the parent Payment object (`payment.amount`) and a second comparison shape (derived-percentage math) — evaluated and explicitly rejected for this change as overscoping risk. A percentage-denominated payout_frequency term is flagged trigger_condition_unverifiable, not silently skipped or misread as a flat amount.
- Fetching, modeling, or storing the parent Razorpay `Payment` object in any form. Nothing in this change reads `GET /v1/payments/:id` or `GET /v1/payments/:id/transfers` — only `GET /v1/transfers` filtered by recipient, which needs no parent-payment context.
- Escrow, Smart Collect, Payment Links, or any other Razorpay product. Route is the only primitive this change touches.
- Cadence-based comparison for Route. A Transfer carries no schedule field; a cadence-shaped payout_frequency term for a transfer-referenced Contract is trigger_condition_unverifiable, not cadence_mismatch — this path never computes an empirical cadence the way the payout path does.
- Risk scoring, severity weighting, reporting, or the evaluation harness — unaffected, same as add-razorpay-crosscheck's own non-goals.

## Decisions

**`RazorpayReferenceType` gains `TRANSFER`.** `contracts/models.py`'s `RazorpayReferenceType` becomes a plain 3-value `TextChoices` (`PAYOUT`, `SUBSCRIPTION`, `TRANSFER`). A transfer-referenced Contract's `razorpay_reference_id` holds the recipient identifier the Transfer history is fetched for — the same "one string field, meaning depends on razorpay_reference_type" convention `fund_account_id` and `subscription_id` already use; no new Contract field is introduced.

**`RazorpayConnector.fetch_transfers` — GET-only, mirrors `fetch_payouts` exactly.**

```python
def fetch_transfers(self, *, recipient_settlement_id: str) -> dict[str, Any]:
    """GET /v1/transfers filtered by recipient_settlement_id (Route Transfer history)."""
    params = {"recipient_settlement_id": recipient_settlement_id}
    try:
        result: dict[str, Any] = self._sdk_client.get(_TRANSFERS_PATH, params)
        return result
    except AttributeError:
        return self._raw_get(_TRANSFERS_PATH, params=params)
```

`_TRANSFERS_PATH = "/v1/transfers"` joins the existing module-level path constants. This is the same shape as `fetch_payouts(fund_account_id=...)` — a GET with one query-param filter, SDK-primary with the existing `_raw_get` fallback — so it needs no new guardrail-test *mechanism*: `test_client.py::test_client_source_contains_no_write_verb_calls` (an AST scan over `client.py`'s whole source) and `test_guardrails.py::test_connector_only_ever_dispatches_get_requests` (a mocked-transport dynamic check) already cover any new method added to this module without modification to the tests themselves, only new assertions calling the new method.

*Filter choice, flagged for verification*: this design follows the recipient_settlement_id-filtered list endpoint (`GET /v1/transfers?recipient_settlement_id=:id`) specifically because it is the one documented list-with-filter shape among the three GET endpoints Route exposes that parallels `fetch_payouts`'s "list this recipient's history" semantics — `GET /v1/transfers/:id` fetches one Transfer by its own id (no history), and `GET /v1/payments/:id/transfers` is keyed by a parent Payment id this design deliberately does not fetch or store (see Non-Goals). Confirm against current Razorpay Route API docs before implementation that `recipient_settlement_id` is populated and filterable pre-settlement for a linked account's Transfers in test mode — see Risks.

**`PlatformRecordType` gains `TRANSFER`.** `razorpay_integration/models.py`'s `PlatformRecordType` becomes a plain 4-value `TextChoices` (`PAYOUT`, `SUBSCRIPTION`, `TOKEN`, `TRANSFER`). No other model change: a fetched Transfer persists as a `PlatformRecord(record_type=PlatformRecordType.TRANSFER, payload=<raw Transfer JSON>, razorpay_created_at=...)`, identical in shape to how a Payout persists today.

**`services.fetch_transfer_history(*, contract) -> list[PlatformRecord]`** — a direct structural copy of `fetch_payout_history`: no-ops (no GET call, no PlatformRecord) for a Contract whose razorpay_reference_type is not `transfer`; otherwise calls `RazorpayConnector().fetch_transfers(recipient_settlement_id=contract.razorpay_reference_id)`, iterates `response["items"]`, and persists one `PlatformRecord(record_type=PlatformRecordType.TRANSFER, ...)` per item inside the same `transaction.atomic()` block pattern.

**`_run_route_crosscheck(*, contract) -> list[MismatchFlag]`** — reuses, unchanged, `_list_payout_frequency_terms`, `_compute_empirical_amount`, `_evaluate_amount_term`, `_create_llm_described_mismatch_flag`, and `_create_trigger_condition_unverifiable_flag`. Three things are new:

1. A small `_is_percentage_term(term) -> bool` helper (unit in `{"percent", "percentage", "pct", "%"}`), checked *before* `_is_amount_term` — today's `_is_amount_term` returns True for "any numeric value whose unit isn't a recognized time unit," which would otherwise misclassify a percentage as a flat amount. This is the concrete guard against the overscoping risk the proposal calls out: without it, a "10% of revenue" term would silently get compared against a Transfer's paise amount as if 10 meant ₹10.00.
2. Term routing: for each payout_frequency term on the Contract, `_is_percentage_term` or `_is_cadence_term` → `_create_trigger_condition_unverifiable_flag` (no Transfer field to diff against either shape); otherwise (a flat-amount term, i.e. `_is_amount_term` and not percentage-shaped) → compared against the empirical Transfer amount exactly as the payout path compares its amount terms today.
3. `_create_missing_platform_evidence_flag`'s `payout_record_count` keyword is renamed to the path-neutral `record_count` (its one call site in `_run_payout_crosscheck` updated to match — a mechanical, behavior-preserving rename) so `_run_route_crosscheck` can call it directly when fewer than 2 Transfer records exist, instead of duplicating a near-identical helper.

`detect_mismatches` gains one more branch:

```python
if contract.razorpay_reference_type == RazorpayReferenceType.TRANSFER:
    fetch_transfer_history(contract=contract)
    return _run_route_crosscheck(contract=contract)
```

**`selectors.py` needs no change.** `get_platform_records_for_contract(*, contract, record_type=None)` already accepts any `record_type` string; `PlatformRecordType.TRANSFER.value` works unmodified. No new selector is introduced for this change.

**`fixtures.py`: `seed_transfer`, test-mode only.**

```python
def seed_transfer(
    *,
    payment_id: str,
    account: str,
    amount_paise: int,
    on_hold: bool = False,
    client: razorpay.Client | None = None,
) -> dict[str, Any]:
    """POST /v1/payments/{payment_id}/transfers - create one test-mode Route Transfer.

    Route requires an already-captured test-mode Payment to attach a
    Transfer to; seeding a demo Payment (via Razorpay's test-mode card/UPI
    flow) is a prerequisite this function does not itself perform.
    """
    sdk_client = client or _test_mode_client()
    data = {"transfers": [{"account": account, "amount": amount_paise, "currency": "INR", "on_hold": on_hold}]}
    result: dict[str, Any] = sdk_client.payment.transfer(payment_id, data)
    return result
```

Follows `seed_payout`'s pattern exactly: a plain keyword-only function, test-mode credentials only, never imported by `services.py` or `client.py` — `tests/test_fixtures_isolation.py`'s existing assertion (`fixtures` absent from `detect_mismatches`'s transitive import graph) already covers this addition with no change to the test's mechanism, only a new function existing in the module it already scans.

**Frontend.** `frontend/src/api/types.ts`'s `RazorpayReferenceType` union gains `"transfer"`; `frontend/src/utils/format.ts`'s `RAZORPAY_REFERENCE_TYPE_LABELS` gains `transfer: "Transfer (Route)"`; `frontend/src/pages/UploadPage.tsx`'s select gains a third `<option value="transfer">Transfer (Route)</option>`, following the existing two-option pattern with no structural change to the component.

## Risks / Trade-offs

- **[Risk] Route/RazorpayX access typically requires business KYB (Know Your Business) approval on the Razorpay account, separate from and beyond whatever unlocked Payouts and Subscriptions for this account.** Route is a distinct product activation from RazorpayX Payouts and Subscriptions/UPI Autopay — an account approved for the latter two is not automatically Route-enabled. → **Mitigation**: verify Route is actually enabled on the demo Razorpay account (dashboard → Route, or a test `GET /v1/transfers` call) *before* attempting a live demo of this capability; if Route access is unavailable in the time remaining, this change still lands as a fully spec'd, tested-against-mocks capability (identical to how `test_client.py`/`test_guardrails.py` mock every Razorpay call today) — a live demo is a stretch goal, not a correctness requirement for this change.
- **[Risk] The `recipient_settlement_id` filter's behavior pre-settlement is unconfirmed against current docs.** A Transfer can be `on_hold` and not yet associated with a settlement, which may mean it doesn't appear in a `recipient_settlement_id`-filtered list until later. → **Mitigation**: treat a thin or empty filtered result the same as any other "insufficient evidence" case — `missing_platform_evidence`, exactly as 0 or 1 Payout is handled today; verify the filter's actual pre-settlement behavior against live Razorpay docs or a sandbox call before or during implementation, and revisit the filter choice (e.g. switching to per-payment `GET /v1/payments/:id/transfers` aggregation) if it proves unusable, without needing a new OpenSpec change for a same-capability implementation adjustment.
- **[Risk] Renaming `_create_missing_platform_evidence_flag`'s `payout_record_count` kwarg to `record_count` touches an existing, already-tested payout-path call site.** → **Mitigation**: mechanical, behavior-preserving rename (the value passed and the flag produced are unchanged); `test_payout_crosscheck.py`'s existing assertions on `missing_platform_evidence` flags catch any regression.
- **[Risk] `on_hold`/`on_hold_until` mean a fetched Transfer's amount may represent money not yet actually released to the recipient.** → **Mitigation**: out of scope for the amount comparison itself — the contract term is about the *split amount*, not the settlement/release outcome. The raw payload (including `status`, `on_hold`, `on_hold_until`) is persisted verbatim in `PlatformRecord.payload` regardless, exactly as `PlatformRecord` already does for every other record type, so the full picture remains auditable even though this comparison doesn't act on hold status.
- **[Risk] Median-based empirical amount can still be skewed by one atypical Transfer in a short history**, the same risk the payout path already accepted. → **Mitigation**: unchanged from add-razorpay-crosscheck — median (not mean) chosen for outlier resistance, fixed by spec, not per-contract configurable.

## Migration Plan

- Add `TRANSFER = "transfer", "Transfer"` to `contracts.models.RazorpayReferenceType` and `razorpay_integration.models.PlatformRecordType`; generate and hand-review one migration per app (`contracts` and `razorpay_integration`) — both are `AlterField`-only migrations updating each field's `choices` metadata, with no data migration and no DDL-visible change on the project's target database backends (Django tracks `choices` in migration state even though it enforces no DB-level constraint from it).
- No new settings: `AMOUNT_MISMATCH_TOLERANCE_PCT` is reused as-is; no route-specific tolerance setting is introduced, keeping one tolerance knob per comparison kind (amount vs. cadence), not per Razorpay product.
- No change to `ENABLE_STAGE_4` gating or to `pipeline.services.run_pipeline` — the route path is reached through the same already-gated `detect_mismatches` call.
- Rollback: reverse both migrations (each is additive-only, so reversal is a plain choices revert) and remove the `TRANSFER` branch from `detect_mismatches`; no phase-1 or add-razorpay-crosscheck model, migration, or requirement is touched by rollback.
