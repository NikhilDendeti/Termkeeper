## Why

The project owner supplied a real OpenAI API key and asked to switch the LLM provider from Claude (Anthropic) to OpenAI, verified against OpenAI's current API docs rather than assumed. This is a pure implementation swap — every pipeline stage's guarantees (forced structured output, quote-grounding, `needs_human_review` escalation) stay identical; only which model answers the call changes. No spec-level behavior changes, so `skip_specs: true` is set in this change's `.openspec.yaml` — every function `core.claude_client` exposes today (`get_structured_completion`, `quote_is_verbatim`) keeps its exact signature and contract, just under a new, provider-neutral module name and a new implementation.

**Non-goals**: this does not change any prompt content, any pipeline stage's decision logic, any threshold, or any test's assertions about behavior — only the mechanism that produces the model call. It does not touch the Razorpay integration (a separate provider, unaffected) beyond adding the `RAZORPAY_WEBHOOK_SECRET` setting the project owner also supplied, which has no consumer yet (no webhook endpoint exists in this codebase) — stored for when one is built, not wired to anything now.

## What Changes

- `core/claude_client.py` is renamed to `core/llm_client.py` and reimplemented against the OpenAI Responses API (`client.responses.create` with `text.format={"type":"json_schema","schema":...,"strict":True}`), verified against OpenAI's current docs at implementation time — not guessed from training-data memory, since the API surface changes over time.
- `quote_is_verbatim` and the dependency-free JSON-schema re-validator (`_validate_against_schema` and helpers) move unchanged — they have no provider dependency.
- Every call site (`pipeline/services.py`, `risk_scoring/services.py`, `razorpay_integration/services.py`, `evaluation/services.py`) updates its import from `core.claude_client` to `core.llm_client`; every test that mocks `core.claude_client.get_structured_completion`/`quote_is_verbatim` updates its patch target to `core.llm_client.*`. No test's assertions about pipeline behavior change — only the module path being patched.
- Settings: `ANTHROPIC_API_KEY`/`CLAUDE_MODEL` become `OPENAI_API_KEY`/`OPENAI_MODEL` (default per current OpenAI docs, overridable via env). `RAZORPAY_WEBHOOK_SECRET` added as a stored-but-unused setting.
- `pyproject.toml`: `anthropic` dependency replaced with `openai`.
- `openspec/config.yaml`'s tech-stack line updated to name OpenAI instead of Claude/Anthropic — the project's own living source of truth must not describe a provider the code no longer calls. Already-written prior changes' `proposal.md`/`design.md` files (which say "Claude") are left as-is — they are a historical record of decisions made at the time, per this project's own convention of never rewriting past change artifacts after the fact.

## Capabilities

### New Capabilities
(none — `skip_specs: true`, pure implementation swap, no observable behavior change)

### Modified Capabilities
(none — see above)

## Impact

- **Renamed**: `core/claude_client.py` → `core/llm_client.py`; `core/tests/test_claude_client.py` → `core/tests/test_llm_client.py`.
- **Changed**: 4 service modules' imports (`pipeline`, `risk_scoring`, `razorpay_integration`, `evaluation`) and every test file that patches the LLM client (a full list is enumerated in design.md, grepped from the real codebase, not guessed).
- **Dependencies**: `openai` added, `anthropic` removed.
- **Credentials**: a real `OPENAI_API_KEY` is now set in the (gitignored) `.env` — this change makes the pipeline capable of running against a real model for the first time in this project's history; that live run is itself part of this change's verification, not left as a future TODO.
