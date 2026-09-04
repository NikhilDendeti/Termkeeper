## Why

Every contract in this system so far has been ingested via a backend CLI command (`manage.py ingest_contract`) run by whoever has terminal access to the machine. There is no way for a person using the frontend — a judge, a reviewer, the project owner's own teammate — to submit their own contract text and see the real pipeline run against it. That's a real gap for a buildathon demo: the strongest possible proof this works is letting someone paste their own contract and watch it get analyzed, not just look at three pre-seeded examples.

**Non-goals**: this does not add file-format parsing beyond plain text (no PDF/DOCX extraction — a `.txt` file can be uploaded and read client-side, or text pasted directly; parsing other formats is a separate, larger scope not requested here). This does not add a background task queue — the analyze endpoint runs the pipeline synchronously, in-request, accepting that a multi-clause contract can take one to several minutes given real LLM latency (5-25s per call, observed in this project's own live runs) — a proper async job queue is future scope if this becomes a real hard requirement, not invented here. This does not change any pipeline stage's logic, thresholds, or guardrails — it only adds a way to trigger the existing, unmodified pipeline from the UI instead of the CLI.

## What Changes

- New `contracts` app endpoint: `POST /contracts/create/` — creates a `Contract` from submitted text and metadata, thin wrapper around the already-existing `contracts.services.create_contract`.
- New `pipeline` app endpoint: `POST /contracts/<uuid:contract_id>/analyze/` — runs the existing, unmodified `pipeline.services.run_pipeline` synchronously against a contract, returning the resulting aggregate report on success. On a mid-run failure (e.g. an LLM provider error), returns a clear, structured error rather than a bare 500 — the pipeline's own partial progress (whatever clauses/terms/scores were already written before the failure) remains in the database exactly as it does today when run via the CLI, and the response tells the caller that.
- New frontend page `/upload`: a form (contract text — paste or `.txt` file read client-side into the same textarea; engagement id, defaulted to an auto-generated value but editable; Razorpay reference type and id, defaulted to sensible placeholders but editable) that calls the two endpoints above in sequence, shows a clear long-running-operation loading state during analysis (this can take minutes), and on completion routes to the existing contract detail page. On a partial failure, shows the error plainly and still links to the partial result rather than dead-ending.

## Capabilities

### New Capabilities
- `contracts/upload-api`: submitting raw contract text and engagement metadata creates a new Contract, ready for analysis.
- `pipeline/analyze-api`: triggering the existing pipeline against a specific contract over HTTP, synchronously, with graceful partial-failure reporting.
- `frontend/upload-page`: the externally observable behavior of the upload UI — what a person can submit and what they see happen.

### Modified Capabilities
(none — no prior change has been archived, nothing under `openspec/specs/` to declare a delta against, per this project's established constraint. This change also does not modify `pipeline/clause-segmentation` or any other existing pipeline-stage capability's behavior — `run_pipeline` itself is called unmodified.)

## Impact

- **New code**: `contracts/views.py`, `contracts/serializers.py`, `contracts/urls.py` (none of these exist yet — `contracts` currently has no HTTP surface at all); `pipeline/views.py`, `pipeline/serializers.py`, `pipeline/urls.py` (same — `pipeline` is CLI-only today); both registered in `config/urls.py`; `frontend/src/pages/UploadPage.tsx` + routing + nav entry + API client additions.
- **No impact** on any pipeline stage's internal logic, any guardrail, or any existing endpoint — this is additive HTTP surface calling already-tested service functions unmodified.
- **Real-world consequence worth naming**: this endpoint will consume real LLM API quota per submission, same as the CLI does today — this project has hit its OpenAI account's rate limit three times in earlier sessions. The upload page's UI must make this cost visible (e.g. "this contract has N clauses, expect roughly N×3 to N×5 model calls"), not hide it.
