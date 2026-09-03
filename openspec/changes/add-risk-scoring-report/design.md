## Context

See proposal.md for motivation. Phase 1 (add-django-foundation) delivered `contracts` (Contract, Clause), `pipeline` (ExtractedTerm, AuditLogEntry, stages 1-3, `run_pipeline(*, contract, from_stage=1)`), and `core.claude_client` (`get_structured_completion`, `quote_is_verbatim`). Phase 2 (add-razorpay-crosscheck) added `razorpay_integration` (PlatformRecord, MismatchFlag with `extracted_term: FK(pipeline.ExtractedTerm)`) and stage 4 (`detect_mismatches`), wired into `run_pipeline` via a function-local import to avoid a circular import between `pipeline` and `razorpay_integration`. Every stage so far persists before the next stage runs — no in-memory handoff between stage functions. This phase must follow the same rule: stage 5 reads Clause/ExtractedTerm/MismatchFlag via selectors, not via arguments threaded from stage 4.

## Goals / Non-Goals

**Goals**
- Score every classified Clause, including clause types (termination, dispute_resolution, indemnity, other) that never carry ExtractedTerm rows and so were invisible to phase 2's cross-check.
- Make severity a reproducible function of persisted inputs, not a free-form LLM judgment, so `reporting/aggregate-report`'s determinism requirement holds without re-querying Claude.
- Make every explanation's factual claims independently verifiable against the clause's own text, with a bounded, observable fallback (one retry, then needs_human_review) when they are not.
- Give the report a single computation path (`reporting/selectors.py::get_contract_report`) consumed identically by the DRF endpoint and the CLI, so the two surfaces cannot drift.

**Non-Goals**
- No synthetic dataset, EvalLabel/EvalRun models, or precision/recall/false-positive-cost scoring — phase 4 (add-evaluation-harness).
- No Django-templates report viewer, clause-expand UI, or guardrail-verification view — phase 5 (add-report-ui).
- No RiskAssessment history/versioning — re-scoring a clause replaces its current RiskAssessment; the full chain of past attempts remains in AuditLogEntry (phase 1), which is never overwritten.
- No admin-configurable criticality weights or severity thresholds — they are fixed module constants in this phase.

## Decisions

**Two new apps: `risk_scoring` (writes) and `reporting` (reads only, no models).**
`risk_scoring` owns RiskAssessment and the scoring service — it is the only app in this phase that writes AI-derived data. `reporting` only composes rows already owned by other apps: RiskAssessment (risk_scoring), MismatchFlag (razorpay_integration), and AuditLogEntry (pipeline). Alternative considered: fold aggregation into `risk_scoring`. Rejected — `risk_scoring` would then falsely appear to own MismatchFlag and AuditLogEntry data it only reads, and the DRF/CLI surface (which has zero models and zero writes) would sit oddly inside a write-owning app. Keeping `reporting` separate also means it can depend on `razorpay_integration` and `risk_scoring` without either of those apps depending back on it.

**`RiskAssessment.clause` is a `OneToOneField`, not a plain `ForeignKey`.**
Exactly one *current* RiskAssessment exists per Clause; re-running stage 5 for a clause is an update-or-create, not an append. A `OneToOneField(Clause, on_delete=models.CASCADE, related_name="risk_assessment")` enforces that invariant at the database level instead of relying on application code to deduplicate. Alternative considered: plain FK allowing a history of assessments per clause. Rejected for this phase — no requirement here needs scoring history, and AuditLogEntry already preserves every individual LLM call+response permanently, which is where a future "show me every past scoring attempt" feature would read from; a `RiskAssessment` history table is deferred, not designed away.

**Severity is computed in Python from a bounded LLM output, never named by the LLM directly.**
The Claude call for stage 5 returns only `asymmetry_score` (a float the schema constrains to [-1, 1]), the explanation's sentence/quote pairs, and an optional rewrite. `risk_scoring/services.py` then computes severity deterministically:
1. `criticality = CRITICALITY_WEIGHTS[clause.clause_type]` — a fixed table: `payment_schedule=1.0, penalty_late_fee=1.0, termination=0.8, indemnity=0.8, auto_renewal=0.6, dispute_resolution=0.5, other=0.3`.
2. `base = abs(asymmetry_score) * criticality` (range [0, 1]).
3. `bumped = min(base + 0.25, 1.0)` if `linked_mismatch_flag_ids` is non-empty, else `bumped = base`.
4. Band the result: `>=0.75` → critical, `>=0.5` → high, `>=0.25` → medium, else → low.
Alternative considered: let the LLM assign the severity label directly, with `asymmetry_score` as a supporting field. Rejected — a label chosen by the model is not reproducible across calls/model versions and cannot satisfy `reporting/aggregate-report`'s "byte-identical across repeated calls" requirement, since that requirement's determinism is only as strong as the RiskAssessment rows it reads. Computing the band from a bounded float in application code makes the mapping unit-testable independent of the model.

**Quote-grounding schema and retry.** The stage-5 structured-output schema requests `{"sentences": [{"text": str, "quote": str}], "asymmetry_score": float, "suggested_rewrite": str | null}`. `score_clause` validates every `quote` with `core.claude_client.quote_is_verbatim(source=clause.clause_text, quote=item["quote"])`. If every quote passes, `explanation = " ".join(s["text"] for s in sentences)` is persisted alongside the computed severity. If any quote fails, `score_clause` calls `get_structured_completion` a second time with the same inputs (the retry is a plain second call inside `score_clause`, not a Claude-side retry mechanism); if the second attempt also has any unbacked quote, severity is forced to `needs_human_review`, `asymmetry_score` is stored as `0.0`, `suggested_rewrite` is `null`, and `explanation` is set to a fixed system-authored string (not model output) describing that the explanation failed verification — so an unverified claim is never persisted as if it were validated.

**needs_human_review inheritance short-circuits before any LLM call.** `score_clause` checks `clause.clause_type` first. If it is `needs_human_review` or `None` (phase 1 classification never resolved it, or explicitly flagged it), `score_clause` returns immediately with `severity=needs_human_review`, `asymmetry_score=0.0`, `suggested_rewrite=None`, and a fixed explanation ("clause was not confidently classified; scoring deferred to human review") — no call to `core.claude_client` is made. This keeps `needs_human_review` meaning the same thing end to end (classification → scoring → report) and avoids spending a Claude call scoring text the pipeline itself could not confidently type.

**Mismatch linkage query.** MismatchFlag has no direct FK to Clause (phase 2: `extracted_term: FK(pipeline.ExtractedTerm)`). `score_clause` (via `risk_scoring/selectors.py::get_linked_mismatch_flags`) resolves linkage as `MismatchFlag.objects.filter(extracted_term__clause=clause)`, evaluated at scoring time — a clause's `linked_mismatch_flag_ids` reflects whichever MismatchFlag rows exist at the moment stage 5 runs for it, not a live/dynamic property recomputed at report time.

**`get_contract_report` lives in `reporting/selectors.py`, not `services.py`.** HackSoft convention reserves `selectors.py` for reads and `services.py` for writes; `get_contract_report` persists nothing — it is a pure query-and-compute function, however complex. Follows convention, no deviation, despite the complexity of the aggregation logic living in a selector.

**`reporting` exposes a thin `APIView`, not a `ViewSet`.** The surface is retrieve-only for a single contract's report and a single contract's audit trail — no list, create, update, or delete semantics exist or are wanted. A `ViewSet` would expose routes (list, create, destroy) that have no meaning here and would need to be manually disabled; a plain `APIView.get()` calling the selector directly is simpler and matches "no business logic in views."

**CLI/API parity is structural, not tested-after-the-fact.** Both `ContractReportAPIView.get()` and `report_contract`'s `handle()` call the exact same `reporting.selectors.get_contract_report(*, contract=...)` and `pipeline.selectors.get_audit_trail(*, contract=...)`. The DRF `ContractReportSerializer` serializes that dict for the API's JSON body; the CLI's `--format json` path calls `json.dumps` on the same dict (via the serializer's `.data` to keep field names identical); only `--format md` has rendering logic not shared with the API, since markdown has no API equivalent.

**Extending `run_pipeline` without a new circular import.** `risk_scoring` depends on `contracts` (Clause) and `razorpay_integration` (MismatchFlag, transitively via ExtractedTerm). `pipeline.services.run_pipeline` must call `risk_scoring.services.score_clause` for every clause after stage 4. Following the precedent phase 2 already set for `detect_mismatches`, this call is a function-local import inside `run_pipeline`'s body, not a module-level import, avoiding any import-order coupling between `pipeline` and `risk_scoring`. `reporting` is never imported by `run_pipeline` — report generation is on-demand (API/CLI), not a pipeline stage, so it needs no stage number and no AuditLogEntry of its own.

**Follows the HackSoft-style service/selector convention; no deviation.** Every write in `risk_scoring` goes through `services.py`; every non-trivial read in both apps goes through `selectors.py`; `RiskAssessment` carries only fields, `Meta`, and a `CheckConstraint`/validator for the asymmetry_score bound — no business logic on the model.

**New Django app: `risk_scoring`**
- Model: `RiskAssessment(id: UUID pk, clause: OneToOneField(Clause, on_delete=CASCADE, related_name="risk_assessment"), severity: CharField(choices=SeverityChoices), asymmetry_score: FloatField(validators=[MinValueValidator(-1.0), MaxValueValidator(1.0)]), explanation: TextField, suggested_rewrite: TextField(null=True, blank=True), linked_mismatch_flag_ids: ArrayField(UUIDField(), default=list, blank=True), created_at: DateTimeField(auto_now_add=True))`, plus a `CheckConstraint(check=Q(asymmetry_score__gte=-1) & Q(asymmetry_score__lte=1))`.
- `services.py`:
  - `score_clause(*, clause: Clause) -> RiskAssessment`
- `selectors.py`:
  - `get_risk_assessment_for_clause(*, clause: Clause) -> RiskAssessment | None`
  - `list_risk_assessments_for_contract(*, contract: Contract) -> QuerySet[RiskAssessment]`
  - `get_linked_mismatch_flags(*, clause: Clause) -> QuerySet[MismatchFlag]`

**New Django app: `reporting`** (no models)
- `selectors.py`:
  - `get_contract_report(*, contract: Contract) -> dict` — returns `{"contract_id": UUID, "overall_risk_score": float | None, "flagged_clauses": list[dict], "platform_mismatches": list[dict], "needs_human_review_clauses": list[dict]}`, ranked by descending severity weight then descending abs(asymmetry_score).
  - `get_full_audit_trail(*, contract: Contract) -> QuerySet[AuditLogEntry]` — thin pass-through to `pipeline.selectors.get_audit_trail`, kept in `reporting` so both the view and the command import from one place.
- `serializers.py`: `ContractReportSerializer(serializers.Serializer)` (plus nested `FlaggedClauseSerializer`, `PlatformMismatchSerializer`, `NeedsHumanReviewClauseSerializer`), `AuditLogEntrySerializer(serializers.Serializer)`.
- `views.py`: `ContractReportAPIView(APIView)` with `get(self, request, contract_id)` calling `contracts.selectors.get_contract` (404 via `Http404`/`get_object_or_404`-style lookup on `DoesNotExist`) then `reporting.selectors.get_contract_report`; `ContractAuditTrailAPIView(APIView)` calling `get_full_audit_trail`. Both thin — no branching business logic beyond the 404 lookup.
- `urls.py`: `contracts/<uuid:contract_id>/report/` and `contracts/<uuid:contract_id>/audit-trail/`, included from the project URLConf.
- Management command: `reporting/management/commands/report_contract.py`, args `--contract-id` (required) and `--format` (`json`|`md`, default `json`), calling the same two selectors as the views; `--format md` renders one markdown section per flagged clause, one for mismatches, one for needs-human-review clauses, one for the audit trail; any other `--format` value raises `CommandError` before any output is written.

## Risks / Trade-offs

- **[Risk]** A strict verbatim-quote gate could force an unexpectedly high fraction of clauses to needs_human_review if the model tends to paraphrase instead of quoting. → **Mitigation**: the prompt instructs the model to copy `quote` substrings directly from the supplied clause_text rather than compose them; only one retry is spent before falling back, bounding cost; the actual false-escalation rate is measured properly in phase 4's evaluation harness, not guessed at here.
- **[Risk]** Hard-coded criticality weights and severity band cutoffs are a single global tuning surface that may not generalize past the buildathon demo corpus. → **Mitigation**: both live as named constants in one module (`risk_scoring/services.py`), so they are easy to locate and change, and every table-driven unit test in tasks.md exercises the boundary values directly.
- **[Risk]** `OneToOneField(Clause)` means re-running stage 5 discards the previous RiskAssessment row instead of keeping a history. → **Mitigation**: AuditLogEntry (phase 1) already records every individual stage-5 prompt/response/latency permanently regardless of how many times a clause is rescored, so the full reasoning history survives even though only the latest RiskAssessment row does; a dedicated history table is a deferred, not abandoned, idea.
- **[Risk]** `overall_risk_score = None` (the all-needs_human_review case) could be misread by a naive consumer as "no risk" if it collapses to a falsy display value. → **Mitigation**: `ContractReportSerializer` declares the field as nullable (not defaulted to 0), and both the API and CLI always render `needs_human_review_clauses` alongside the score so the gap is visible, not silent.

## Migration Plan

- Deploy: add `risk_scoring` and `reporting` to `INSTALLED_APPS`; run `manage.py makemigrations risk_scoring` (hand-reviewed) and `manage.py migrate risk_scoring` — this creates the RiskAssessment table only, with a FK into the existing `contracts_clause` table; `reporting` has no migrations. Wire `reporting.urls` into the project URLConf and extend `pipeline.services.run_pipeline` with the stage-5 call.
- Backfill: for any contracts already carried through stages 1-4 in an existing environment, run `manage.py run_pipeline --contract-id <id> --from-stage 5` (or a bulk variant) to populate RiskAssessment rows before report endpoints are relied on for those contracts; this is not required for correctness — `get_contract_report` returns empty `flagged_clauses`/`needs_human_review_clauses` lists and `overall_risk_score=None` for a contract with no RiskAssessment rows yet, it does not error.
- Rollback: `reporting` has zero migrations, so removing it from `INSTALLED_APPS` and deleting its URL include is fully safe with no data loss. `risk_scoring` rollback is `manage.py migrate risk_scoring zero` followed by removing it from `INSTALLED_APPS`; because every RiskAssessment row is fully re-derivable by re-running stage 5 against the still-intact Clause/ExtractedTerm/MismatchFlag data, this drop is non-destructive to any other app's data.

## Open Questions

- Exact prompt wording and few-shot examples for the stage-5 severity/asymmetry/explanation call are a tuning concern properly resolved against phase 4's evaluation harness (precision/recall against labeled synthetic contracts), not fixed here — this design only fixes the schema, the verification gate, and the deterministic severity formula those examples must produce inputs for.
