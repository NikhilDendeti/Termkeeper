## Context

See proposal.md - Why. `core.llm_client.quote_is_verbatim` is called by four sites across three apps
(`pipeline`, `risk_scoring`, `razorpay_integration`) as the one shared grounding primitive. This change
touches only that one function's internal comparison.

## Goals / Non-Goals

**Goals:**
- Stop whitespace-only source-formatting artifacts (line-wrapped text, table-cell extraction landing
  cells on separate lines) from causing a false verbatim-match failure.
- Implement the fix once, in the shared validator, so all four call sites benefit uniformly without
  divergent per-stage normalization.

**Non-Goals:**
- Not fuzzy matching, not semantic/embedding similarity, no edit-distance tolerance. A substituted word,
  changed number, or omitted/added content must still fail exactly as it does today.
- Does not change any caller's retry count, escalation control flow, or when `quote_is_verbatim` is
  invoked — only what happens inside the function.

## Decisions

**Algorithm: collapse whitespace runs to one space, strip ends, then substring-check.**

    import re
    _WHITESPACE_RUN = re.compile(r"\s+")

    def _normalize_whitespace(text: str) -> str:
        return _WHITESPACE_RUN.sub(" ", text).strip()

    def quote_is_verbatim(source: str, quote: str) -> bool:
        return _normalize_whitespace(source).find(_normalize_whitespace(quote)) != -1

`\s` matches space, tab, newline, carriage return, form feed, and vertical tab — any run of one or more
is collapsed to exactly one space, and the result is stripped of leading/trailing whitespace before the
substring check. This is applied to *both* `source` and `quote`, so a quote that itself contains a raw
newline (also possible from LLM output) is normalized the same way as the source.

**What does NOT change:**
- Actual word/character content must still match exactly. `"net 30 days"` vs `"net 45 days"` still fails
  — normalization only touches whitespace *between* tokens, never the tokens themselves.
- No stemming, casing changes, punctuation stripping, or fuzzy/approximate matching of any kind.
- The function's signature (`quote_is_verbatim(source: str, quote: str) -> bool`), return type, and every
  caller's usage (arguments passed, when it's called, what happens on `True`/`False`) are unchanged.
- `pipeline.services.segment_contract`/`extract_terms`'s retry count (still exactly one retry),
  `risk_scoring.services.score_clause`'s retry-then-needs_human_review fallback, and
  `razorpay_integration.services._generate_mismatch_description`'s retry-then-deterministic-template
  fallback are all untouched — they still call the same function the same way; only what that function
  decides changes for whitespace-only cases.

**Why collapse-to-one-space rather than strip-all-whitespace.** Stripping every whitespace character
entirely (rather than collapsing to one space) would make `"netdays"`-style token-boundary loss
indistinguishable from a real match, e.g. it would make `"net 30days"` match `"net 30 days"` — silently
tolerating a missing space between two real words, which is a genuine content difference, not a
formatting artifact. Collapsing to exactly one space preserves "these are two separate tokens" while
discarding "how many spaces/newlines separate them," which is the actual formatting-artifact this change
targets.

## Risks / Trade-offs

- **[Risk]** Collapsing whitespace could theoretically let a quote spanning two genuinely-unrelated
  parts of the source (e.g. two different table rows joined only by whitespace) match as if contiguous.
  → **Mitigation**: accepted as inherent to any substring-based grounding check (this is already true
  today for two adjacent words with normal single-space separation); whitespace-run collapsing doesn't
  meaningfully widen this — it does not remove non-whitespace characters, so two source spans separated by
  actual content (not just whitespace) still cannot be bridged by a normalized quote.
- **[Risk]** A quote's internal double space that was actually meaningful (e.g. inside a code block or
  ASCII table embedded in `raw_text`) is now tolerated. → **Mitigation**: out of scope for a payment-terms
  contract analyzer; no such content is expected in a Contract's `raw_text` in this project.

## Migration Plan

No model or migration changes. Pure function-body change in `core/llm_client.py`, immediately effective
for every caller on next deploy — no rollout sequencing needed.
