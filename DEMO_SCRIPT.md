# Termkeeper — 5-Minute Pitch Video Script
### Razorpay AI Buildathon — Open Track (Track 5)

Verified buildathon requirements (fetched live from razorpay.com/buildathon/, not assumed): a **public repo**, a **5-minute pitch video**, **architecture documentation**, and **track-specific metrics**. Judging emphasizes four things named on the page: **Problem Taste, Build Quality, AI Judgment, Failure Recovery** ("what broke + how it was fixed, described in the pitch video"). This script is built to hit all four explicitly, using only things that are real and currently verifiable in the running app — nothing staged.

---

## Two honest constraints, and the decision

1. **OpenAI quota is currently at 0** (daily rate limit exhausted). A live "upload a contract and watch the AI analyze it" moment will fail on camera right now. Script around already-analyzed contracts (built into the script below) — don't attempt a fresh upload on camera unless you've added billing beforehand.
2. **No real Razorpay mismatch is shown** — a live Payout demo needs a RazorpayX source account number (separate business KYB approval this account doesn't have), so this isn't attempted. **Decision: don't fake it — mention stage 4 as fully built and tested, gated off in this recording, and show the code + guardrail proving it's write-safe.** This is honest, and per the hackathon-judging research, judges explicitly reward that kind of precision over a blurred claim.

---

## Pre-recording checklist

- [ ] Both dev servers running (`localhost:8000` backend, `localhost:5173` frontend)
- [ ] Browser window sized/zoomed so text is readable on a recording (no dev tools open)
- [ ] Close unrelated tabs/notifications
- [ ] Do one full silent run-through first (per hackathon-judging research: lock the exact path 4 hours before deadline if possible, rehearse it 5 times, record a backup take)
- [ ] Have `ARCHITECTURE.md` and this script open in a second window to glance at, not read from

---

## The script — 5:00 total

### 0:00–0:50 — Cold open: a real failure, not a hypothetical (Problem Taste + Failure Recovery, up front)

**Say, over your face or a blank screen — don't open the app yet:**

> "A freelance dev shop sends a client a payment-milestone table in a proposal. Standard stuff — 25% on kickoff, 25% on delivery. I built a system to read that contract and check it against what actually happens on Razorpay. I tested it on my own real business documents. And on the very first real one, it broke."

**Switch to the browser. Navigate to the OudhTrade contract's Document tab:** `http://localhost:5173/contracts/069e5b2c-16e9-4c23-8a86-4b35982543cb`

> "This is a real proposal I uploaded. See this banner? The system flagged it for human review instead of guessing. Here's why that happened, and why I think it's actually the right behavior, not a bug."

**Point to the reason text.** Explain in one breath: the payment table's cells wrapped onto separate lines when copy-pasted; the AI's proposed clause boundary differed from the source by one newline; the system's verbatim-matching guardrail caught that and refused to proceed rather than risk misplacing a real financial clause.

> "That's the core design principle: never guess on a payment term. Escalate instead. I fixed the root cause — whitespace-tolerant matching — and I'll show you the fix later. But I'm leading with the failure because it's real, and because it proves the guardrail actually works under real-world mess, not just clean test fixtures."

*(This single beat hits "Problem Taste" — a specific, real, relatable failure — and pre-loads "Failure Recovery" with a true story, not a manufactured one.)*

---

### 0:50–1:20 — What it actually does (30 seconds, architecture at a glance)

**Say, screen still on the app or a quick cut to `ARCHITECTURE.md`:**

> "Termkeeper reads a vendor or freelance contract, extracts what it promises about payment — amounts, cadence, penalties — and checks those promises against Razorpay's own live data: real Payout history, real Subscription and UPI Autopay config. Six stages: segmentation, classification, extraction, Razorpay cross-check, risk scoring, and an aggregate report. Every stage's output is grounded — the AI can't claim something the source text doesn't literally say."

---

### 1:20–3:30 — Live proof (2:10 — the meat of the video, three genuinely live moments)

**Open `demo-subscription-mismatch`'s Document tab**, and be direct about scope on camera:

> "Stage 4 cross-checks contract terms against two kinds of real Razorpay data: RazorpayX Payout history for empirical cadence and amount drift, and Subscriptions/UPI Autopay for an exact config-field diff. It's fully built and tested against the real SDK's interface. I'm keeping it gated off in this recording rather than firing live API calls on camera — but here's the code path, and here's the guardrail proving it can never write."

**Then show these three things — all genuinely live on camera, not pre-recorded, zero API cost:**

1. **A flagged clause with a quote-grounded explanation** (~25s). Open `demo-milestone-drift` (`http://localhost:5173/contracts/171177ba-8221-4d6a-86a8-40de0bae9de0`), click into the Reasoning Chain tab, open one flagged clause.
   > "Every risk explanation quotes the contract text directly — the system can't say 'this clause is risky' unless that's a verbatim quote from the actual contract. If it can't ground a claim, it falls back to a deterministic template instead of hallucinating a justification."

2. **The guardrail, live.** Navigate to `/guardrail`, click **Re-run scan**.
   > "This re-scans the Razorpay integration's source code right now, on camera — not a cached badge. AST-based static analysis proving the path touching Razorpay's API never issues a write call."

3. **Break the audit trail on purpose, live** (~60s — the strongest live moment in the video). Switch to a terminal:
   ```bash
   python manage.py verify_audit_chain
   ```
   > "Every AI call writes into a SHA-256 hash chain, one per contract. Let me prove that's real, not decorative — I'll add two entries through the actual write path, verify the chain, then tamper with one and watch it get caught."

   Run this (adjust the contract lookup if you used a different one — `demo-milestone-drift` is already in the repo):
   ```bash
   python manage.py shell -c "
   from contracts.models import Contract
   from pipeline.services import create_audit_log_entry
   c = Contract.objects.get(engagement_id='demo-milestone-drift')
   create_audit_log_entry(contract=c, clause=None, stage=1, prompt_version='live-demo', llm_response_raw={'demo': 'entry one'}, model_name='demo', latency_ms=100)
   create_audit_log_entry(contract=c, clause=None, stage=1, prompt_version='live-demo', llm_response_raw={'demo': 'entry two'}, model_name='demo', latency_ms=100)
   "
   python manage.py verify_audit_chain
   ```
   > "Two real chained entries, verified." Then, on camera, tamper with one:
   ```bash
   python manage.py shell -c "
   from contracts.models import Contract
   from pipeline.models import AuditLogEntry
   c = Contract.objects.get(engagement_id='demo-milestone-drift')
   e = AuditLogEntry.objects.filter(contract=c, entry_hash__isnull=False).order_by('chain_sequence').first()
   e.llm_response_raw = {'demo': 'TAMPERED'}
   e.save()
   "
   python manage.py verify_audit_chain
   ```
   > "Same command. It catches it — exact entry, exact reason. Not a log that just sits there; a chain that proves its own integrity."

   **After the take, clean up** (don't leave test rows in before you finish recording, or before submitting):
   ```bash
   python manage.py shell -c "
   from contracts.models import Contract
   from pipeline.models import AuditLogEntry
   c = Contract.objects.get(engagement_id='demo-milestone-drift')
   AuditLogEntry.objects.filter(contract=c, prompt_version='live-demo').delete()
   "
   ```

*(This block hits Build Quality and AI Judgment directly — deterministic guardrails where it matters, LLM judgment scoped and grounded everywhere else. Being upfront that stage 4 is gated off, and showing exactly why, is itself a Build-Quality signal — judges distrust a demo that blurs "live" and "built." The hash-chain break is the one moment in the whole video where you cause a failure on purpose and the system catches it in real time — that's a live "Failure Recovery" proof, not just a story about a past one.)*

---

### 3:30–4:15 — Failure Recovery, closed out (45 seconds)

**Say, back on the OudhTrade contract or a split view of the before/after:**

> "Back to that failure from the opening. The bug: the AI's proposed clause read '(INR) 1. Kickoff' with a space, but the source text had a newline there — 'and one whitespace character broke an otherwise-correct extraction. I traced it to the exact character, wrote a spec change first — not just a patch — collapsing whitespace runs before the verbatim check, while keeping it strict on anything that's an actual content change. [N] new tests confirm both halves: the real bug case now passes, and a genuinely altered clause — a changed number, a substituted word — still correctly fails and gets escalated."

*(State the real, current test count here — check `pytest -q` and `npm run test` immediately before recording, don't reuse a number from earlier in the day.)*

---

### 4:15–4:45 — The evidence, fast (30 seconds)

**Quick cuts, 5-7 seconds each:**
- `/about` page: pipeline stages, clause taxonomy, OpenSpec change count, live test counts
- Terminal: `pytest -q` scrolling to a green pass line (real, run live or a clean recent recording)
- `openspec/changes/` folder listing, or one proposal.md — "every feature here was specced — problem, requirements, design tradeoffs — before a line of code"

> "Everything on screen right now is checkable. Not a claim — a running test suite, a live guardrail scan, a spec history you can read."

---

### 4:45–5:00 — Close (15 seconds)

> "Termkeeper: contract promises, checked against what a payment rail actually did — not an invoice, not a self-report, the rail's own API. It doesn't guess when it's not sure. That's the whole pitch."

---

## Recording tips (from what actually wins hackathon judging, verified via research)

- **A working demo beats a polished one.** Don't over-produce; a clean screen recording with your real voice beats a slide deck.
- **Judges reward a real problem over a technically impressive but narrow one** — the cold-open story does this work; don't bury it.
- **If anything might glitch live, record it in advance and narrate over the recording** rather than risk a dead demo — judges don't penalize a pre-recorded fallback, they penalize an unrecovered live failure.
- **Rehearse the exact click-path 3-5 times** before the real take so there's no dead air finding the right page.
- **Keep it at or under 5:00** — going over reads as not respecting the format.

## Submission

The buildathon page lists: public repo, 5-minute video, architecture doc, track-specific metrics. You have all four (`ARCHITECTURE.md`, this test suite, the live guardrail). Upload the recording to YouTube (unlisted) or Loom/Drive per whatever the actual submission form asks for, and push this repo public before submitting — that's a step only you can do (see the earlier note on setting up a git remote).
