## 1. Implementation

- [ ] 1.1 Implement `_normalize_whitespace` and update `quote_is_verbatim` in `core/llm_client.py` per
      design.md's algorithm; update its docstring to describe the new whitespace-collapsing behavior
      accurately (spec: Verbatim clause extraction)
- [ ] 1.2 Update `core/tests/test_llm_client.py`: replace the existing test that asserted a
      whitespace-only difference is NOT verbatim (now intentionally false) with one asserting it IS,
      and add focused new tests — exact match, newline-vs-space (incl. the real table-extraction case
      from proposal.md), multiple-spaces/tab, leading/trailing whitespace, and a genuinely-different-words
      case proving content matching is still strict
- [ ] 1.3 Add a `pipeline/tests/test_segmentation.py` test mirroring the real table-extraction case
      (mocked LLM response differs from raw_text only by whitespace/newline placement), asserting
      segmentation now persists the Clause instead of escalating to needs_human_review; verify the
      existing non-whitespace escalation test in the same file still passes unchanged
- [ ] 1.4 Grep the repo for any other place assuming the old strict-whitespace behavior; none found in
      research beyond the one test in 1.2 (already fixed there)

## 2. Verification

- [ ] 2.1 Run `openspec validate normalize-verbatim-whitespace --strict` and resolve anything it flags
- [ ] 2.2 Run `python -m pytest -q` from repo root and confirm every previously-passing test still
      passes, plus the new tests
- [ ] 2.3 Run `mypy core pipeline` and confirm zero errors
