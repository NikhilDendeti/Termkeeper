# ContractGuard Architecture

**AI Payment Terms & Vendor Risk Analyzer — Razorpay AI Buildathon (Open Track)**

This document is the architecture deliverable for the buildathon submission. It
describes how a contract turns into a risk report, what stops the system from
guessing or hallucinating along the way, and why the codebase is shaped the way
it is. Everything below is grounded in the actual source tree and the
project's own OpenSpec change history (`openspec/changes/*/design.md`), not
aspirational design — where a claim could go stale, it was re-checked against
the running code on 2026-09-04 (see [Verification notes](#verification-notes)
at the end).

---

## 1. The pipeline: six stages, database-only handoff

A contract moves through six stages. Each stage is one small, independently
callable, typed service function — never a step that only exists inside a
bigger function's local variables.

```
 Contract.raw_text
        |
        v
 ┌──────────────────┐
 │ 1. SEGMENTATION   │  pipeline.services.segment_contract
 │                   │  reads:  Contract.raw_text
 │                   │  writes: Clause rows (verbatim spans) + AuditLogEntry(stage=1)
 └──────────────────┘
        |  (next stage re-reads from DB — nothing passed in memory)
        v
 ┌──────────────────┐
 │ 2. CLASSIFICATION │  pipeline.services.classify_clause
 │                   │  reads:  Clause.clause_text
 │                   │  writes: Clause.clause_type / confidence / rationale
 │                   │          + AuditLogEntry(stage=2)
 └──────────────────┘
        |
        v
 ┌──────────────────┐
 │ 3. EXTRACTION     │  pipeline.services.extract_terms
 │                   │  reads:  classified Clause
 │                   │  writes: ExtractedTerm rows (cadence, amount, trigger,
 │                   │          notice period) + AuditLogEntry(stage=3)
 └──────────────────┘
        |
        v
 ┌──────────────────┐
 │ 4. RAZORPAY       │  razorpay_integration.services.detect_mismatches
 │    CROSS-CHECK    │  reads:  ExtractedTerm rows (via pipeline selector)
 │                   │  writes: PlatformRecord (raw API payload, verbatim)
 │                   │          + MismatchFlag + AuditLogEntry(stage=4)
 │                   │  gated by settings.ENABLE_STAGE_4 (see §7)
 └──────────────────┘
        |
        v
 ┌──────────────────┐
 │ 5. RISK SCORING   │  risk_scoring.services.score_clause
 │                   │  reads:  Clause + ExtractedTerm + linked MismatchFlag rows
 │                   │  writes: RiskAssessment (severity, asymmetry_score,
 │                   │          quote-grounded explanation) + AuditLogEntry(stage=5)
 └──────────────────┘
        |
        v
 ┌──────────────────┐
 │ 6. AGGREGATE      │  reporting.selectors.get_contract_report
 │    REPORT         │  reads-only: RiskAssessment + MismatchFlag + AuditLogEntry
 │                   │  writes:  nothing — a pure query/compute rollup
 └──────────────────┘
        |
        v
   overall_risk_score, flagged_clauses, platform_mismatches,
   needs_human_review_clauses  →  served identically to report_ui,
                                   the DRF JSON API, and the CLI
```

Stage 6 is deliberately not a pipeline stage with its own `AuditLogEntry` —
it's on-demand (API/CLI), computed fresh from whatever the first five stages
already persisted.

### Why database-only, no in-memory handoff

Every stage function reads its inputs by querying the database (via a
`selectors.py` function), never by receiving the previous stage's Python
return value as an argument. `pipeline.services.run_pipeline(*, contract,
from_stage=1)` calls the five stage functions in order, but the only thing it
threads between them is the `contract` object itself.

This is a deliberate, named design rule going back to the very first change
(`add-django-foundation/design.md`):

> "Make every pipeline stage a plain, typed, independently callable service
> function — no stage depends on another stage's Python return value, only on
> rows the prior stage already wrote to the database. This is what makes
> `run_pipeline --from-stage N` and per-clause human-review resubmission
> possible starting from phase 3 onward."

The trade-off is named explicitly too, in that same design's Risks section:
the database round-trip per stage costs more than passing Python objects
would. It's accepted on purpose — contract volumes are small (tens of
clauses), so the extra round-trips are cheap, and what they buy is real:

- **Resumability.** `run_pipeline(*, contract, from_stage=4)` re-runs stage 4
  onward without re-running 1–3, because stage 4 gets everything it needs by
  querying rows stages 1–3 already committed.
- **Human-review resubmission.** A clause the pipeline couldn't confidently
  classify or extract can be corrected and re-run from whichever stage needs
  to re-run, without reconstructing upstream state in memory.
- **A crash mid-pipeline loses at most the in-flight stage**, not the whole
  run — everything before it is already durable.

This same rule is reaffirmed by name in every later phase's design doc: stage
4's design notes it "must follow the same rule: it reads persisted
`ExtractedTerm` rows via a selector, not via an argument passed in-process
from stage 3," and stage 5's design repeats the identical constraint for
`Clause`/`ExtractedTerm`/`MismatchFlag`.

---

## 2. App-per-bounded-context structure

One Django app per bounded context — never one monolithic app. This is stated
as a hard rule in `openspec/config.yaml`'s project-wide `context` block and
followed without deviation in every phase's design doc.

```
config/                  Django project config (settings split base/local/production)
core/                    No models. Shared infra only:
                          llm_client.py  — the ONE OpenAI wrapper every stage calls through
                          (get_structured_completion, quote_is_verbatim)

contracts/                Contract, Clause — entities that exist independent of any AI run
pipeline/                  ExtractedTerm, AuditLogEntry — stages 1-3 + orchestration (run_pipeline)
razorpay_integration/       PlatformRecord, MismatchFlag — stage 4, the only app that talks to Razorpay
risk_scoring/                RiskAssessment — stage 5
reporting/                    no models — read-only: stage 6, reasoning-chain, guardrail scan, DRF views
evaluation/                    EvalLabel, EvalRun — synthetic dataset + eval harness (own app, one-way deps)

report_ui/                Django-templates UI, reads only through `reporting`
frontend/                 React + TypeScript + Vite UI, its own project, reads only over HTTP
```

Dependency direction is one-way and gets called out explicitly at each phase
boundary to avoid circular imports: `pipeline` depends on `contracts`;
`razorpay_integration` depends on `pipeline` and `contracts`; `risk_scoring`
depends on `contracts` and (transitively) `razorpay_integration`; `reporting`
depends on `risk_scoring`, `razorpay_integration`, and `pipeline` but nothing
depends on `reporting`; `evaluation` depends on all four pipeline-owning apps
and nothing depends back on `evaluation`.

Two places need a stage-owning app to call into a *later* app
(`pipeline.services.run_pipeline` calling `razorpay_integration.services.
detect_mismatches` after stage 3, then `risk_scoring.services.score_clause`
after stage 4) without creating a circular top-level import. Both are solved
the same documented way: a **function-local import** inside `run_pipeline`'s
body rather than a module-level one, so the import resolves only once both
modules have already finished loading. The `add-razorpay-crosscheck` design
doc calls this "a pragmatic, explicitly-scoped exception documented here
rather than a silent workaround," and considers and rejects two alternatives
(an `AppConfig.ready()` signal-dispatch registry, and moving `run_pipeline`
into a new ownerless orchestration module) as unnecessary indirection for a
five-phase hackathon build.

### The `services.py` / `selectors.py` convention

Every app follows the same HackSoft-style split, stated once in
`openspec/config.yaml` and then followed "with no deviation" (the literal
phrase every later design doc uses) in every subsequent app:

| File | Contains | Rule |
|---|---|---|
| `services.py` | Every **write** | Plain functions, not classes — one function per use case, keyword-only args. Kept small: "split rather than growing a function to cover a second use case" (`config.yaml`, apply-operation guidance). |
| `selectors.py` | Every non-trivial **read** | Also plain, typed functions. `reporting`'s `get_contract_report` is a pure query-and-compute function and stays in `selectors.py` even though it's non-trivial, because it persists nothing. |
| `models.py` | Fields, `Meta`, constraints, `clean()`-level validation only | No cross-model orchestration lives on a model. |
| `views.py` | Thin DRF `APIView`s | Look up the object (404 on a miss), call one selector, serialize, return — no business logic in the view. |

Every service function and selector is fully typed (mypy-clean, per
`config.yaml`). Tests live next to the code they test, one test module per
service/selector/endpoint, using pytest + pytest-django + factory_boy.
Migrations are hand-reviewed before commit — never autogenerated and left
unread.

---

## 3. SQLite, no Docker — the reasoning, verbatim

This wasn't a default; it's a recorded decision. From `openspec/config.yaml`'s
`context` block:

> "Tech stack: Django + Django REST Framework, SQLite (Django's built-in
> backend, db.sqlite3 — no Docker, no external database service; chosen so
> the buildathon demo runs with zero infrastructure setup on any machine)..."

And the fuller justification, from `add-django-foundation/design.md`'s
Decisions section:

> "**Database: SQLite (Django's built-in backend), not PostgreSQL.**
> `db.sqlite3` as a single local file, no external service, no Docker, no
> connection configuration for the buildathon demo or local dev... Alternative
> considered: PostgreSQL via Docker. Rejected for this project: the buildathon
> demo needs to run on a judge's or teammate's machine with zero
> infrastructure setup, and nothing in phases 1–5 needs a Postgres-only
> feature (no full-text search, no concurrent-write tuning, no `ArrayField`).
> If a future phase needs true concurrent writers or JSON-path querying at
> scale, revisit then — not a cost worth paying now."

Every `JSONField` in the schema (`ExtractedTerm.value_structured`,
`AuditLogEntry.llm_response_raw`, `PlatformRecord.payload`, `EvalRun.
precision_recall_f1`/`cost_report`) runs on SQLite's JSON1-backed
`JSONField` and is stored/read back whole — nothing queries inside the JSON
blobs. That's the concrete feature-parity check behind "nothing in phases 1–5
needs a Postgres-only feature."

---

## 4. Guardrails enforced by code, not documentation

Two guardrails exist as *running code*, checkable by anyone, not just as
claims in a README.

### 4.1 No live writes — a live AST scanner

`reporting.selectors.scan_razorpay_guardrail()` (confirmed present at
`reporting/selectors.py:415`) statically proves the production Razorpay code
path issues no write call. Concretely, on every invocation it:

1. Parses `razorpay_integration/client.py` (and the rest of the scanned
   production-path files) with `ast.parse` — **it never imports or executes
   the scanned module**, so running the scan itself makes no network call.
2. Walks every `ast.Call` node in the parse tree.
3. Flags a violation if the call's method name matches a known write-verb
   pattern (`post`, `patch`, `put`, `delete`, …) or a known SDK write-call
   target (e.g. `payouts.create`).
4. Excludes `razorpay_integration/fixtures.py` from the scan by default —
   and a caller can prove that exclusion is real (not just an empty default
   list) by passing a `scanned_paths` tuple that deliberately includes
   `fixtures.py` and asserting it never survives in the result.

This is exposed live at `/guardrail` in **both** UIs — it re-scans the actual
source files on the request, not a cached "we checked once" claim. The write
path that legitimately exists (`razorpay_integration/fixtures.py`, used only
by test-mode demo/fixture seeding, invoked only from management commands or
test setup — never from `run_pipeline`) is architecturally isolated from
`detect_mismatches` and a dedicated test asserts `fixtures` never appears in
that function's transitive import graph.

`razorpay_integration/client.py`'s `RazorpayConnector` exposes exactly three
methods reachable from the production path — `fetch_payouts(fund_account_id)`,
`fetch_subscription(subscription_id)`, `fetch_token(token_id)` — all GET.

### 4.2 No ungrounded explanations — quote-grounding + fallback

Every AI-generated risk explanation or mismatch description must quote its
own source clause **verbatim** before it is persisted. The check is one
shared function, `core.llm_client.quote_is_verbatim(source, quote) -> bool`,
called from four places: `pipeline.services.segment_contract` (stage 1),
`pipeline.services.extract_terms` (stage 3), `risk_scoring.services.
score_clause` (stage 5), and `razorpay_integration.services.
_generate_mismatch_description` (mismatch descriptions). If the model's
proposed quote isn't actually present in the source text, the pipeline never
guesses: a risk explanation falls back to `needs_human_review` (severity
forced to that value, `asymmetry_score` stored as `0.0`, and a fixed,
system-authored explanation string replaces the model's unverified one — not
a second model call dressed up as ground truth), and a mismatch description
falls back to a deterministic template.

**A real, current example of this guardrail being strengthened, from this
session:** `quote_is_verbatim` used to be a byte-for-byte substring check
(`source.find(quote) != -1`) with zero tolerance. A real uploaded contract
had a payment-milestone table whose cells landed on separate lines once
pasted into `raw_text`; the model (correctly) reproduced that clause with the
line-break collapsed to a single space, which failed the strict check on
formatting alone and escalated a genuinely-verbatim clause to
`needs_human_review`. The fix (`openspec/changes/normalize-verbatim-whitespace`)
is deliberately narrow — it does **not** add fuzzy or semantic matching. It
collapses runs of whitespace (spaces/tabs/newlines) to a single space and
strips leading/trailing whitespace in *both* `source` and `quote` before the
substring check, so line-wrapping and table-extraction artifacts stop causing
false escalations while a substituted word, changed number, omitted phrase,
or added content still fails exactly as before. The current implementation
(`core/llm_client.py:249`):

```python
def quote_is_verbatim(source: str, quote: str) -> bool:
    """Return whether `quote` appears within `source`, ignoring whitespace formatting.
    ...only tolerance: runs of whitespace ... are collapsed to a single space,
    and leading/trailing whitespace is stripped, before comparing..."""
    return _normalize_whitespace(source).find(_normalize_whitespace(quote)) != -1
```

This one change is instructive of how the guardrail evolves generally: the
fix landed in a single shared function used by all four call sites, exactly
once — not four separate patches — because `core.llm_client` is the one place
this check exists.

---

## 5. Two frontends — a recorded decision, not drift

Two working UIs exist against the same backend, and this is documented as a
deliberate reversal, not an oversight:

- **`report_ui`** — Django templates, served at `/report/...` on the Django
  dev server. Built first (`add-report-ui`); it's still the reference
  implementation for what the reasoning chain, audit log, and guardrail view
  should show.
- **`frontend`** — React + TypeScript + Vite ("ContractGuard"), its own dev
  server on `:5173`, calling the backend only over a CORS-enabled JSON API.
  Added later (`add-react-frontend`), once the project owner explicitly asked
  for a genuinely separate frontend/backend split.

`report_ui`'s original design chose Django templates *specifically to avoid*
a second project. `add-react-frontend/design.md` records the reversal
directly as an ADR rather than silently retiring the older UI:

> "That design.md chose Django-templates specifically to avoid a second
> project. The project owner has since explicitly asked for a genuinely
> separate frontend and backend. Rather than silently reversing the earlier
> ADR, this one records the reversal directly: `report_ui` is not removed or
> deprecated — its templates, views, and 36 tests continue to serve their
> existing routes unchanged... Alternative considered: retire `report_ui` and
> replace it outright. Rejected — it's already built and tested, and removing
> verified work to satisfy a stack preference (rather than a behavior change)
> is not this project's convention."

Both UIs read exclusively through `reporting` — no read logic is duplicated
between them. When the React app needed reasoning-chain and guardrail-scan
reads that had originally been written inside `report_ui/selectors.py`, those
functions (`get_contract_reasoning_chain`, `scan_razorpay_guardrail`, and
their supporting dataclasses) were *relocated* to `reporting/selectors.py`
rather than duplicated, specifically because `reporting` cannot depend
backward on `report_ui`. Both UIs are exercised by their own test suites and
are expected to keep passing — confirmed current: **460 backend tests
passing** (`python -m pytest -q`, includes `report_ui`, `contracts`,
`pipeline`, `razorpay_integration`, `risk_scoring`, `reporting`,
`evaluation`, `core`) and **70 frontend tests passing across 11 files**
(`npm run test`, from `frontend/`), both re-run live for this document.

---

## 6. Measured results — the evaluation harness

**Status: not obtained.** `EvalRun.objects.count() == 0` in `db.sqlite3` as of
this report (re-verified directly against the database file while writing
this document). There is no real precision/recall/severity-calibration number
to report yet, and none is fabricated here to fill the gap.

What **is** complete: the entire harness itself, and every layer needed to
surface its results once it has run.

- **Backend**: `evaluation` app — `EvalLabel`/`EvalRun` models,
  `evaluation.services.generate_synthetic_contract` /
  `label_synthetic_contract` / `run_eval`, the manifest-hash integrity check
  (`get_heldout_manifest`, aborting with no `EvalRun` row written on a hash
  mismatch), `evaluation/views.py`, `evaluation/serializers.py`,
  `evaluation/urls.py` — all present and covered by tests (`evaluation/tests/
  test_get_latest_eval_run.py`, `test_serializers.py`, `test_views.py`,
  among others), all currently passing.
- **Frontend**: `frontend/src/pages/EvaluationPage.tsx` +
  `EvaluationPage.test.tsx` — renders the metrics once an `EvalRun` exists,
  already verified end-to-end against both the empty-state case (live browser
  check, no `EvalRun` present — exactly today's real state) and a realistic
  full-data case (in the test file, against representative mock data).

### Why the number is missing: a real, externally-verified OpenAI rate limit

This is not a mock, a skipped step, or a code defect. What actually happened
in this session:

1. Ran, for real:
   ```
   python manage.py eval generate-dataset --dataset eval/v1 \
       --export evaluation/fixtures/dataset/v1/contracts.json
   ```
   This made genuine OpenAI Responses-API calls (model: `gpt-4o-mini`, from
   the project's own `.env` — confirmed present as `OPENAI_MODEL=gpt-4o-mini`)
   and successfully persisted 7 of the required 36 synthetic contracts
   (`synthetic-v1-001` … `synthetic-v1-007`, each with real `Clause` +
   `EvalLabel` rows from a real LLM-phrased contract) before failing with a
   real `openai.RateLimitError` (HTTP 429):

   > "Rate limit reached for gpt-4o-mini ... requests per day (RPD): Limit
   > 50, Used 50, Requested 1. Please try again in 28m48s."

2. The limit was independently re-verified with a second, minimal real API
   call roughly five minutes later — it returned the identical 429 with the
   same "Used 50/50, retry in 28m48s" message, confirming the quota was
   genuinely exhausted by this and earlier work today, not a fluke.

3. The dataset requirement is real and non-trivial, not an artificially high
   bar: the committed `evaluation/fixtures/eval/v1/heldout_manifest.json`
   requires held-out contracts up to `synthetic-v1-033` (confirmed —
   its `heldout_engagement_ids` list runs `synthetic-v1-006` through
   `synthetic-v1-033`), and dataset size is hard-floored at 30 by
   `evaluation/services.py`. A compliant run needs at least 33 real phrasing
   calls just for dataset generation, plus further real calls for pipeline
   stages 2/3/5 (classification/extraction/risk-scoring) on the 7 held-out
   contracts to produce non-degenerate `risk_severity` metrics — far more
   than the remaining daily quota permits right now.

4. The 7 partially-generated contracts were cleaned up (`Contract`/`Clause`/
   `EvalLabel` cascade-deleted, 84 rows) so a future clean retry of the exact
   same two commands won't collide on `engagement_id` — confirmed: the live
   database currently holds zero `synthetic-v1-*` engagement IDs (its 7
   `Contract` rows are all pre-existing demo/upload data, unrelated to this
   eval attempt).

5. A background job was started (via the Monitor tool) that waits out the
   reported ~29-minute reset window and then, for real: runs
   `eval generate-dataset` (`dataset_version=v1`, count 36), runs
   `pipeline.services.run_pipeline(from_stage=2)` against each of the 7
   held-out contracts, loads the (LLM-free, deterministic) Razorpay fixture
   matrix via `evaluation.services.load_razorpay_fixture_scenarios`, and
   finally runs `eval run`. This report was finalized before that job could
   complete, so its outcome is not reflected here — the job does not continue
   after the session ends. Script left at (repo-root-relative paths, safe to
   re-run manually):
   ```
   C:\Users\Nikhil\AppData\Local\Temp\claude\C--Users-Nikhil-OneDrive-Desktop-2\6bfb7797-4bbc-4590-8c92-3631129ca050\scratchpad\run_real_eval.py
   ```

### To finish this once the daily quota resets

From the repo root:

```bash
python manage.py eval generate-dataset --dataset eval/v1 \
    --export evaluation/fixtures/dataset/v1/contracts.json
python manage.py eval run --dataset eval/v1
```

`EvaluationPage` will then show the real numbers automatically — this path is
already verified end-to-end against both the empty-state case (live browser
check) and a realistic full-data case (`EvaluationPage.test.tsx`).

---

## 7. Razorpay integration — current status, honestly

Stage 4 (`razorpay_integration`) is **fully implemented and tested, but
currently gated off**, pending a separate, manually-supervised live demo run
that has not yet happened.

**What's real and done:**
- `RazorpayConnector` (`razorpay_integration/client.py`) — GET-only reads:
  RazorpayX Payout history (for the empirical cadence/amount cross-check —
  chosen specifically because RazorpayX exposes no queryable payout-schedule
  config endpoint, only history) and Subscription + Token config (for the
  exact field-diff cross-check on UPI Autopay mandates — period, interval,
  per-cycle amount cap, expiry).
- The AST-based guardrail scan (§4.1) proving no write call exists anywhere
  in the code path `detect_mismatches` can reach.
- The full test suite mocks every call against the real Razorpay SDK's
  interface shape — not a hand-rolled stand-in.

**What has not happened, as of this document:** a live run against a real
Razorpay *test-mode* account. The gate is a real settings flag,
`ENABLE_STAGE_4`, read in `config/settings/base.py` and checked in
`pipeline/services.py` before stage 4 runs. Confirmed by direct inspection of
the project's own `.env` (not `.env.example`): **`ENABLE_STAGE_4=False`** in
the currently configured environment — stage 4 is genuinely off right now,
not just capable of being turned off. When disabled, `run_pipeline` degrades
gracefully to stages 1–3 only, by design (`add-razorpay-crosscheck/design.md`:
"Gate the stage-4 call behind a settings flag ... so `run_pipeline` degrades
gracefully to stages 1-3 only if this app needs to be disabled without a code
rollback").

This is a deliberate separation, not an oversight: automated tests validate
the integration's *shape and guardrail* against a mocked SDK interface;
turning `ENABLE_STAGE_4` on for a real test-mode account is left as an
explicit, manually-supervised step, not something folded silently into CI or
this document's numbers. No live Razorpay run is claimed to have occurred in
this document, because none has.

---

## Verification notes

Every concrete claim above that could go stale was checked directly against
the running repository while writing this document, rather than trusted from
the source docs alone:

- `reporting.selectors.scan_razorpay_guardrail` — confirmed present at
  `reporting/selectors.py:415`, behavior read from source.
- `core.llm_client.quote_is_verbatim` — confirmed whitespace-tolerant in the
  current source (`core/llm_client.py:249`), matching the
  `normalize-verbatim-whitespace` OpenSpec change (present, uncommitted, in
  `openspec/changes/`).
- `ENABLE_STAGE_4=False` — confirmed by reading the project's actual `.env`
  directly (not `.env.example`, which defaults to `True`).
- `OPENAI_MODEL=gpt-4o-mini` — confirmed in the same `.env`.
- `EvalRun.objects.count() == 0` — confirmed by querying `db.sqlite3`
  directly (`evaluation_evalrun` table, 0 rows).
- No `synthetic-v1-*` contracts remain in the database — confirmed by
  querying `contracts_contract` directly (7 rows, all pre-existing
  demo/upload data, none matching that engagement-id pattern).
- `evaluation/fixtures/eval/v1/heldout_manifest.json` requiring
  `synthetic-v1-033` — confirmed by reading the file directly.
- Test counts — the README states 448 backend / 65 frontend; this session's
  own work (visible in `git status`: new `evaluation/views.py`,
  `evaluation/serializers.py`, `EvaluationPage.tsx`/`.test.tsx`,
  `UploadPage.tsx`, `contracts/views.py`, etc.) has moved past that snapshot,
  so both suites were re-run live for this document instead of quoting the
  README figure: **460 backend tests passing** (`python -m pytest -q`) and
  **70 frontend tests passing across 11 files** (`npm run test`, from
  `frontend/`). `python manage.py check` reports no issues.
- `INSTALLED_APPS` in `config/settings/base.py` — confirmed to list exactly
  `core`, `contracts`, `pipeline`, `razorpay_integration`, `risk_scoring`,
  `reporting`, `evaluation`, `report_ui`, matching §2's structure diagram.

Where this document's numbers (460 / 70) differ from README.md's (448 / 65),
this document's are the fresher, live-measured ones — re-run either command
yourself for the current figures as the codebase continues to grow.
