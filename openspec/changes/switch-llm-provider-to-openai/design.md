## Context

`core/claude_client.py` exists today with two public functions consumed across four apps: `get_structured_completion(system_prompt: str, user_content: str, schema: dict[str, Any], *, prompt_version: str) -> dict[str, Any]` and `quote_is_verbatim(source: str, quote: str) -> bool`. Every caller (`pipeline`, `risk_scoring`, `razorpay_integration`, `evaluation`) depends only on these two signatures, never on Anthropic-specific types — this is precisely why phase 1's design chose one shared client wrapper. That decision is what makes this swap contained to one module's internals plus a mechanical rename, rather than touching pipeline/scoring logic anywhere.

**Verified OpenAI API shape** (fetched from OpenAI's current docs at implementation time, not assumed from training data): the Responses API's structured-outputs mode —
```python
from openai import OpenAI
client = OpenAI(api_key=settings.OPENAI_API_KEY)
response = client.responses.create(
    model=settings.OPENAI_MODEL,
    input=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ],
    text={
        "format": {
            "type": "json_schema",
            "name": "structured_output",
            "schema": schema,
            "strict": True,
        }
    },
)
```
Parsing the result: iterate `response.output` for the item with `type == "message"`; within its `content`, an item with `type == "refusal"` means the model declined (raise `StructuredCompletionError` with the `refusal` text) and an item with `type == "output_text"` carries the JSON string to `json.loads`. Separately check `response.status == "incomplete"` (e.g. `incomplete_details.reason == "max_output_tokens"`) before trusting any output at all. Supported models: GPT-4o and later; current OpenAI guidance recommends `gpt-5.6` for new projects as of this implementation — set as the default via `settings.OPENAI_MODEL`, overridable via the `OPENAI_MODEL` env var so it can be swapped without a code change if OpenAI's guidance moves on.

## Goals / Non-Goals

**Goals:**
- Zero behavior change to any pipeline stage's decisions, thresholds, or persisted data shapes — this is an implementation swap, not a feature change.
- The new client's error handling is at least as defensive as the old one: a refusal, an incomplete response, or a schema-violating result must all raise `StructuredCompletionError`, never be silently accepted.
- Reuse `_validate_against_schema`/`_value_matches_json_type`/`_JSON_TYPE_TO_PYTHON` verbatim — they were already provider-agnostic.

**Non-Goals:**
- No prompt content changes anywhere in `pipeline`, `risk_scoring`, or `razorpay_integration` — the system prompts and schemas those modules build are provider-agnostic inputs to `get_structured_completion` and don't need to know which provider answers them.
- No retry/backoff changes beyond what already existed per-caller (e.g. segmentation's one-retry-then-`needs_human_review` logic lives in `pipeline/services.py`, not in the client — unaffected).

## Decisions

**Rename `core/claude_client.py` → `core/llm_client.py`.** A module named after a specific vendor while calling a different vendor's API is a real clean-code defect, not cosmetic — and every call site is already known and grep-enumerated (below), with the existing 400+ test suite as the safety net for the mechanical rename. Alternative considered: keep the filename for "minimal diff." Rejected — this project has held a consistent clean-code bar across five phases; a misleadingly-named module is exactly the kind of thing that bar exists to prevent, and the risk is well-mitigated by the full-suite verification this change already requires.

**`get_structured_completion`'s new body**, per the verified API shape above: build the `OpenAI` client, call `client.responses.create(...)`, then:
1. If `response.status == "incomplete"`: raise `StructuredCompletionError` naming `response.incomplete_details.reason`.
2. Find the `type == "message"` item in `response.output`; if none, raise (mirrors the old "wrong stop_reason" case).
3. Within its `content`, if a `type == "refusal"` item exists, raise `StructuredCompletionError` with its `refusal` text (mirrors the old "wrong tool name"/rejection case).
4. Otherwise find the `type == "output_text"` item, `json.loads` its `.text`; if parsing fails or the result isn't a `dict`, raise (mirrors the old "input not a dict" case).
5. Run the parsed result through the unchanged `_validate_against_schema` before returning — defense in depth stays identical.

**Exact real files to touch** (grepped from the live codebase, not estimated):
- Rename + reimplement: `core/claude_client.py` → `core/llm_client.py`; `core/tests/test_claude_client.py` → `core/tests/test_llm_client.py` (mock `openai.OpenAI`/`client.responses.create` instead of `anthropic.Anthropic`/`client.messages.create`; keep the same test *cases* — happy path, refusal/malformed-equivalent failures, `quote_is_verbatim`'s three cases — only the mock target changes).
- Import + patch-target updates only (no logic changes): `pipeline/services.py` + its tests (`test_segmentation.py`, `test_classification.py`, `test_extraction.py`, `test_orchestration.py`, `test_run_pipeline_command.py`); `risk_scoring/services.py` + its tests (`test_scoring.py`, `test_severity_formula.py`, `test_pipeline_integration.py`); `razorpay_integration/services.py` + its tests (`test_payout_crosscheck.py`, `test_subscription_crosscheck.py`, `test_mismatch_flagging.py`, `test_guardrails.py`, `test_pipeline_integration.py`); `evaluation/services.py` + its tests (`test_dataset_generation.py`, `test_generate_synthetic_contract.py`, `test_labeling.py`, `test_heldout_split.py`, `test_razorpay_fixture_matrix.py`, `test_eval_command.py`, `test_dataset_snapshot_export.py`); `reporting/tests/test_selectors.py` if it references the client at all (verify, don't assume from the grep alone).
- `config/settings/base.py`: replace `ANTHROPIC_API_KEY`/`CLAUDE_MODEL` with `OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")` / `OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6")`; add `RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")` (stored, unused — no webhook endpoint exists yet).
- `pyproject.toml`: remove `anthropic`, add `openai`.
- `.env.example`: mirror the real `.env`'s new variable names (never the real key value).
- `openspec/config.yaml`: update the "Tech stack" line's LLM description from Claude/Anthropic to OpenAI.

**Do not edit** any prior change's `proposal.md`/`design.md`/`specs/` under `openspec/changes/` — those are historical record, per this project's established convention (see e.g. `add-react-frontend`'s design.md treating `add-report-ui`'s decision as history to supersede explicitly, never silently rewrite).

## Risks / Trade-offs

- **[Risk]** A live model swap changes actual model behavior (phrasing, occasional edge-case judgment) even though the code contract is unchanged — a clause that scored `medium` under Claude might score `high` under GPT-5.6 for the same text. → **Mitigation**: none of this project's tests assert on live-model *content* (they all mock the client and assert on the wrapper's *handling* of a given mocked response) — so no test becomes flaky from this, and the eval harness (precision/recall/F1) is the mechanism designed to catch a real quality regression, not unit tests.
- **[Risk]** `gpt-5.6` is taken from current docs fetched at implementation time — if OpenAI's guidance or model availability changes, a hardcoded default could go stale. → **Mitigation**: `OPENAI_MODEL` is an env var with a default, not a hardcoded literal in the client — changeable with no code edit.
- **[Risk]** Real API key now lives in `.env` (gitignored) and was pasted in plain text in this conversation. → **Mitigation**: written only to `.env`, never echoed back in full in any response; `.env` was already gitignored before this change (verified, unaffected by this change).

## Migration Plan

No database migration. Rollout order: (1) reimplement and rename the client + its own tests, verify in isolation; (2) update the four service modules' imports; (3) update every test's patch target; (4) run the full suite (400+ tests, zero behavior change expected in any assertion); (5) as this change's own final verification — not a follow-up — actually run the real pipeline once against a real contract using the real `OPENAI_API_KEY`, proving genuine end-to-end function, not just mocked-test correctness. Rollback: revert the rename + the four import changes + settings; `ANTHROPIC_API_KEY`/`anthropic` dependency would need re-adding if ever reverted, but nothing about this change is destructive to data (no models, no migrations).
