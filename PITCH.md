# Payment Terms & Vendor Risk Analyzer — Pitch

*Razorpay AI Buildathon, Open Track. Verified against the real codebase, claim by claim — see `openspec/changes/` for the full spec-driven build history.*

## 1. Problem Statement

Freelancers and small vendors lose money not because a payment fails, but because the contract governing that payment was unfair or unclear from day one — and almost nobody reviews these terms before agreeing to them.

Every freelance engagement, vendor agreement, or subscription mandate has payment terms buried inside it: when you get paid, what triggers a penalty, what counts as a valid termination, what happens on a dispute. These clauses are usually written by whichever side has the lawyer — which is rarely the freelancer or the small vendor. The result:

- Milestone payments held back on vague "not satisfied" language with no defined resolution path
- Termination clauses that let the client walk away instantly, while the freelancer owes 30 days' notice
- Penalty and late-fee clauses that don't match how the platform is actually configured
- Auto-renewal or recurring-mandate terms nobody reads until the money's already moved

This isn't a payment-*failure* problem — payments succeed. It's a **payment-terms risk problem**: money moves exactly as configured, but the configuration was unfair or the signer didn't understand what they agreed to.

## 2. Why This, Why Now

- Every other track is clustered around payment *failure*. This is a different failure mode — the payment succeeds, but the terms behind it were bad. Structurally uncrowded.
- It's checkable against something real: Razorpay's test-mode APIs let you create real payouts and a real UPI Autopay mandate — so the agent can compare what the contract says against what's *actually happened* (payout history) or what's *actually configured* (mandate config), and flag the mismatch either way. No payout-schedule object exists to fetch on Razorpay's side; this pitch doesn't imply one does.
- It reuses real standing in this problem space — a freelance-marketplace co-founder who also freelances personally.

## 3. Target User & Scope

**Primary user**: a freelancer, gig worker, or small vendor about to sign or configure something involving recurring or milestone-based money movement.

**Scope**: both Razorpay categories are built, fully, deliberately — because they cover two different moments in a payment's lifecycle that neither one alone can:

- **Subscriptions + UPI Autopay** — checks a recurring mandate's real config *before* the first charge fires.
- **RazorpayX Payouts** — checks milestone/one-off payment history for drift *after* money has started moving.

A freelance engagement rarely uses only one of these. Building both took real discipline to keep each one thin and correct: 26 passing tests across both cross-check paths, zero live network calls in the automated suite, zero stubs.

## 4. Solution Flow

1. **Clause segmentation** — split the contract into individually addressable, verbatim clauses.
2. **Clause classification** — tag each by type: payment schedule, termination, penalty/late fee, dispute resolution, auto-renewal, indemnity, or other.
3. **Payment-term extraction** — pull the concrete terms: payout frequency, milestone triggers, penalty amounts, notice periods.
4. **Cross-check against the platform** — two different ways, depending on how the engagement is paid:

   | Path | What's actually checked | When it can flag something real |
   |---|---|---|
   | Subscriptions + UPI Autopay | Real mandate config — billing period, interval, per-cycle amount cap, expiry — fetched directly and diffed exactly against the contract | Before the first auto-debit, once the mandate exists |
   | RazorpayX Payouts | Empirical cadence/amount — median across executed payouts — diffed against the contract's stated terms | After ≥2 real payouts; before that, it flags "insufficient history," not a guess |

   Milestone-trigger language ("due on client approval") has no Razorpay-side field to check on either path — the tool says so explicitly (`trigger_condition_unverifiable`) rather than implying a comparison happened.
5. **Risk scoring** — per clause, severity and asymmetry, with a plain-English explanation grounded in a verbatim quote from the clause text.
6. **Aggregate report** — overall risk score, top flagged clauses, platform mismatches, and rewrite suggestions where warranted.

## 5. Core Features

| Feature | What it does |
|---|---|
| Clause-level risk flags | Severity + a plain-English explanation, quote-grounded, verified before persisting |
| Contract-vs-platform mismatch detector | Two paths (above) tied to Razorpay's actual rails, not a generic legal tool |
| Rewrite suggestions | For clauses scored medium/high/critical, when the model judges a concrete rewrite meaningfully improves it — low-severity flags never get one |
| Aggregate risk score | A single severity-weighted score per contract; needs-human-review clauses excluded from the number and listed separately |
| Audit trail | Every LLM-backed stage writes an entry recording its parsed output, prompt version, model name, and latency |

## 6. Guardrails

- The agent never auto-signs, auto-negotiates, or modifies any live payout/subscription — advisory output only, enforced by a live static scanner (`manage.py verify_guardrail`) that parses the integration's source with `ast` and fails on any write-verb call — not just documented as a promise.
- Every risk explanation and every mismatch description must quote the source text verbatim before being persisted, checked programmatically. A risk explanation that fails retries once, then downgrades to `needs_human_review`. A mismatch description that fails retries once, then falls back to a deterministic templated description.
- A genuinely ambiguous clause is flagged "needs human review" rather than force-scored.

## 7. Evaluation Plan

- 30-50 synthetic contracts generated from a deterministic, seeded generator — every clause's ground-truth risk label comes from the same parameters that generated its text, not hand-labeled per contract. Exactly reproducible, immune to rater fatigue.
- Held-out split enforced by a committed, hash-verified manifest — the eval run refuses to proceed if the manifest doesn't match the current dataset.
- Precision, recall, F1, and a severity-calibration score, reported separately — never blended into one number. False-positive and false-negative cost reported explicitly, broken down by clause type and mismatch type.
- The repeatable, automated eval suite runs the real detection code against a committed set of canned Razorpay payloads — deliberately, so it's deterministic and never flaky in front of judges. A one-time live run against Razorpay's actual sandbox is the stronger visual for the pitch video itself — a manual demo step, not part of the automated suite.

## 8. Why This Is the Strong Version

- A real problem with a real mechanism of harm — not a hypothetical.
- Demoable end-to-end against Razorpay's actual test-mode APIs.
- Built on genuine standing in this problem space.
- Not just scoped — built, tested, and independently verified: 373+ passing tests across the full six-stage pipeline, both Razorpay cross-check paths, the evaluation harness, and a separate React frontend, with every guardrail enforced by code rather than asserted in prose.
