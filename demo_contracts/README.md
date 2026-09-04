# Demo contracts

The source text for the three contracts seeded into the local demo database (`db.sqlite3`, gitignored — not this text) and shown in both UIs.

| File | Engagement ID | Razorpay reference | What it demonstrates |
|---|---|---|---|
| [`demo_contract_1_milestone_drift.txt`](demo_contract_1_milestone_drift.txt) | `demo-milestone-drift` | payout | The one fully real, AI-processed example — every clause genuinely classified and risk-scored by `gpt-5.6`/`gpt-4o-mini`, no fixture data anywhere. Deliberately asymmetric termination clause (client terminates instantly, contractor owes 30 days) for the model to catch. |
| [`demo_contract_2_subscription_mismatch.txt`](demo_contract_2_subscription_mismatch.txt) | `demo-subscription-mismatch` | subscription | A UPI Autopay mandate scenario — contract states ₹18,000/month, the linked mandate fixture is configured for ₹15,000, producing a real `amount_mismatch`. |
| [`demo_contract_3_fair_control.txt`](demo_contract_3_fair_control.txt) | `demo-fair-control` | payout | A genuinely balanced contract, paired with matching payout records — the "true negative" control proving the detector doesn't flag a fair contract. |

## Re-seeding

These contracts are not persisted in git as database rows (`db.sqlite3` is gitignored, per-machine local dev data). To load them into a fresh database:

```bash
python manage.py ingest_contract demo_contracts/demo_contract_1_milestone_drift.txt \
  --engagement-id demo-milestone-drift --razorpay-reference-type payout --razorpay-reference-id pout_demo_001
python manage.py run_pipeline --contract-id <the id printed above>
```

Contract 1 above is safe to fully re-run through the real pipeline (needs `OPENAI_API_KEY` set). Contracts 2 and 3's mismatch/control platform data is currently fixture-seeded rather than run through a live Razorpay sandbox (no Razorpay credentials configured in this environment) — see `PITCH.md` and `README.md` for that distinction.
