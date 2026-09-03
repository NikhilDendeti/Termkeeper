## 1. Core client: rename and reimplement

- [ ] 1.1 `pip install openai` into `.venv`, remove `anthropic` from `pyproject.toml` dependencies and add `openai`, and verify `pip install -e .` (or equivalent) still resolves cleanly
- [ ] 1.2 Rename `core/claude_client.py` to `core/llm_client.py` and reimplement `get_structured_completion` against the OpenAI Responses API exactly per design.md's verified shape (refusal handling, incomplete-status handling, output_text parsing, then the unchanged `_validate_against_schema`), keeping `quote_is_verbatim` and the schema-validation helpers byte-for-byte unchanged
- [ ] 1.3 Rename `core/tests/test_claude_client.py` to `core/tests/test_llm_client.py`, update every mock to target `openai.OpenAI`/`client.responses.create` instead of `anthropic.Anthropic`/`client.messages.create`, keep the same test cases (happy path; refusal; incomplete/malformed response; `quote_is_verbatim`'s exact-match/paraphrase/whitespace cases), and verify `pytest core/ -q` passes

## 2. Update call sites (imports only, no logic changes)

- [ ] 2.1 Update `pipeline/services.py`'s import from `core.claude_client` to `core.llm_client`; update the patch targets in `pipeline/tests/test_segmentation.py`, `test_classification.py`, `test_extraction.py`, `test_orchestration.py`, `test_run_pipeline_command.py`; verify `pytest pipeline/ -q` passes with the same test count as before
- [ ] 2.2 Update `risk_scoring/services.py`'s import; update patch targets in `risk_scoring/tests/test_scoring.py`, `test_severity_formula.py`, `test_pipeline_integration.py`; verify `pytest risk_scoring/ -q` passes with the same test count as before
- [ ] 2.3 Update `razorpay_integration/services.py`'s import; update patch targets in `razorpay_integration/tests/test_payout_crosscheck.py`, `test_subscription_crosscheck.py`, `test_mismatch_flagging.py`, `test_guardrails.py`, `test_pipeline_integration.py`; verify `pytest razorpay_integration/ -q` passes with the same test count as before
- [ ] 2.4 Update `evaluation/services.py`'s import; update patch targets in `evaluation/tests/test_dataset_generation.py`, `test_generate_synthetic_contract.py`, `test_labeling.py`, `test_heldout_split.py`, `test_razorpay_fixture_matrix.py`, `test_eval_command.py`, `test_dataset_snapshot_export.py`; check `reporting/tests/test_selectors.py` for any reference and update if present; verify `pytest evaluation/ reporting/ -q` passes with the same test count as before

## 3. Settings and config

- [ ] 3.1 Replace `ANTHROPIC_API_KEY`/`CLAUDE_MODEL` with `OPENAI_API_KEY`/`OPENAI_MODEL` (default `gpt-5.6`) in `config/settings/base.py`, add `RAZORPAY_WEBHOOK_SECRET` (stored, unused), and verify `manage.py check` passes
- [ ] 3.2 Update `.env.example` to match the real `.env`'s new variable names (no real values), and update `openspec/config.yaml`'s tech-stack line to name OpenAI

## 4. Full verification and real live run

- [ ] 4.1 Run the full backend suite (`pytest -q`) and confirm every test passes with the same total count as before this change (zero net test change, only patch-target renames) — grep the codebase afterward for any remaining `claude_client`/`anthropic`/`ANTHROPIC_API_KEY` reference outside `openspec/changes/*` historical docs and confirm none remain
- [ ] 4.2 Run `mypy` across every touched app and verify zero errors
- [ ] 4.3 With the real `OPENAI_API_KEY` now in `.env`, actually run `manage.py run_pipeline` against one real contract end to end (stages 1-3 at minimum; stage 4 stays disabled per `ENABLE_STAGE_4=False` since Razorpay keys are commented out; stage 5 requires stage 4's output structurally — verify what actually happens and report it precisely, don't assume) and confirm real `Clause`/`ExtractedTerm`/`AuditLogEntry` rows are created from a genuine model response, not a mock — this is the first real end-to-end run in this project's history and is this change's actual proof of correctness, not optional
- [ ] 4.4 Run `openspec validate switch-llm-provider-to-openai --strict` and verify it passes
