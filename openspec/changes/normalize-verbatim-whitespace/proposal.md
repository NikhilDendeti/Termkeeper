## Why

A real user uploaded a genuine business document with a payment-milestone table. When the
document was copy-pasted into `raw_text`, the table's cells landed on separate lines, so the
source text contains:

    ...% of Total
    Amount
    (INR)
    1. Kickoff — Planning & Design On signing & engagement kickoff 25% ₹2,50,000
    2. Core Development...

Stage 1 segmentation asked the model to reproduce this table row as one clause, and the model
proposed:

    "(INR) 1. Kickoff — Planning & Design On signing & engagement kickoff 25% ₹2,50,000"

— collapsing the newline between "(INR)" and "1. Kickoff" into a single space, which is exactly
what a model does with line-wrapped or table-extracted source text. `core.llm_client.quote_is_verbatim`
does a zero-normalization exact substring check (`source.find(quote) != -1`), so this genuinely-present
clause failed verbatim matching, failed again on the one allowed retry, and the whole contract was
escalated to `needs_human_review` with zero clauses persisted. This is a spec-compliant escalation
under the current spec, not a bug in the escalation logic — but it means any real-world document
whose text arrives with re-flowed whitespace (a PDF table, a Word table, hard line wraps) will keep
tripping this gate on formatting alone, not on any genuine content problem.

**Non-goals**: this is not fuzzy or semantic matching. A clause with a substituted word, a changed
number, an omitted phrase, or added content must still fail verbatim matching exactly as it does
today — only runs of whitespace (spaces, tabs, newlines) are tolerated, collapsed to a single space
before comparison. Nothing about *what words* must match changes, only how *whitespace between words*
is compared.

## What Changes

- `core.llm_client.quote_is_verbatim(source, quote)` normalizes both `source` and `quote` — collapsing
  every run of whitespace to a single space and stripping leading/trailing whitespace — before doing the
  substring check, instead of comparing the raw strings byte-for-byte.
- This is implemented exactly once, in the shared validator, so every consumer benefits uniformly and
  consistently without each stage inventing its own normalization: `pipeline.services.segment_contract`
  (stage 1, the case above), `pipeline.services.extract_terms` (stage 3 term-extraction grounding),
  `risk_scoring.services.score_clause` (stage 5 risk-explanation grounding), and
  `razorpay_integration.services._generate_mismatch_description` (mismatch-description grounding) all call
  `quote_is_verbatim` and all stop false-escalating on whitespace-only source-formatting artifacts.
- No caller's signature, return type, retry/escalation control flow, or invocation site changes — only
  `quote_is_verbatim`'s internal string comparison.

## Capabilities

### Modified Capabilities
- `pipeline/clause-segmentation`: "Verbatim clause extraction" now collapses whitespace runs before
  comparing a proposed clause against the source, rather than requiring a byte-for-byte match — see
  `specs/pipeline/clause-segmentation/spec.md`.

### New Capabilities
(none — this change modifies existing verbatim-matching behavior only.)

## Impact

- **Changed code**: `core/llm_client.py` (`quote_is_verbatim` body + docstring only).
- **Changed tests**: `core/tests/test_llm_client.py` (one existing test's assertion was testing the exact
  behavior being intentionally changed, replaced; new focused tests added),
  `pipeline/tests/test_segmentation.py` (one new test for the real table-extraction case).
- **No impact** on `pipeline.services`' retry-count/escalation control flow, on
  `risk_scoring/services.py` or `razorpay_integration/services.py` business logic, or on any model,
  migration, or API surface — this is a pure internal-comparison change in one shared function.
