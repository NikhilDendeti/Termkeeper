"""Write-path service functions for the `pipeline` app.

Every write to an ExtractedTerm/AuditLogEntry (and, transitively, to a
Contract/Clause via `contracts.services`) goes through a function here.
Each stage function is independently callable and hands data to the next
stage only by writing it to the database — no stage depends on another
stage's Python return value — so `run_pipeline(..., from_stage=N)` and a
future per-clause human-review resubmission can resume at any stage. See
design.md (add-django-foundation) - Goals.
"""

from __future__ import annotations

import time
from typing import Any

from django.conf import settings
from django.db import transaction

from contracts import selectors as contracts_selectors
from contracts import services as contracts_services
from contracts.models import Clause, ClauseType, Contract
from core import llm_client
from pipeline.models import AuditLogEntry, ExtractedTerm, PipelineStage, TermType

# ---------------------------------------------------------------------------
# Stage 1: segmentation
# ---------------------------------------------------------------------------

_SEGMENTATION_PROMPT_VERSION = "clause-segmentation-v1"
_SEGMENTATION_MAX_ATTEMPTS = 2

_SEGMENTATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clauses"],
    "additionalProperties": False,
}

_SEGMENTATION_SYSTEM_PROMPT = (
    "You split a contract's raw text into an ordered sequence of clauses. "
    "Each clause's `text` MUST be reproduced character-for-character from "
    "the source text - do not paraphrase, summarize, correct, or re-flow "
    "whitespace. Keep a clause and all of its sub-bullets together as one "
    "unit; never split a single clause across multiple entries - "
    "classifying a multi-topic clause is a later stage's responsibility. "
    "Return the clauses in the order they appear in the source text."
)


def segment_contract(*, contract: Contract) -> list[Clause]:
    """Stage 1: split `contract.raw_text` into verbatim, ordered Clause rows.

    Calls the model once; if any proposed clause cannot be found verbatim in
    `contract.raw_text`, retries once with the same inputs. If validation
    still fails after the retry, marks the Contract `needs_human_review`
    and persists no Clause for this call. Writes exactly one
    AuditLogEntry (stage=1) either way.

    See specs/pipeline/clause-segmentation/spec.md.
    """
    result: dict[str, Any] = {}
    proposed_texts: list[str] = []
    all_verbatim = False
    total_latency_ms = 0

    for _attempt in range(_SEGMENTATION_MAX_ATTEMPTS):
        started_at = time.monotonic()
        result = llm_client.get_structured_completion(
            _SEGMENTATION_SYSTEM_PROMPT,
            contract.raw_text,
            _SEGMENTATION_SCHEMA,
            prompt_version=_SEGMENTATION_PROMPT_VERSION,
        )
        total_latency_ms += int((time.monotonic() - started_at) * 1000)

        proposed_texts = [item["text"] for item in result["clauses"]]
        all_verbatim = all(
            llm_client.quote_is_verbatim(contract.raw_text, text) for text in proposed_texts
        )
        if all_verbatim:
            break

    _create_audit_log_entry(
        contract=contract,
        clause=None,
        stage=PipelineStage.SEGMENTATION,
        prompt_version=_SEGMENTATION_PROMPT_VERSION,
        llm_response_raw=result,
        latency_ms=total_latency_ms,
    )

    if not all_verbatim:
        contracts_services.mark_contract_needs_human_review(
            contract=contract,
            reason=(
                "Stage 1 segmentation: a proposed clause could not be found "
                "verbatim in the contract's raw text after one retry."
            ),
        )
        return []

    clauses: list[Clause] = []
    with transaction.atomic():
        for index, text in enumerate(proposed_texts):
            clauses.append(
                Clause.objects.create(contract=contract, sequence_index=index, clause_text=text)
            )
    return clauses


# ---------------------------------------------------------------------------
# Stage 2: classification
# ---------------------------------------------------------------------------

_CLASSIFICATION_PROMPT_VERSION = "clause-classification-v1"

# The labels the model may propose. `needs_human_review` is deliberately
# excluded - it is a gate outcome this service applies, never a model
# prediction - see specs/pipeline/clause-classification/spec.md.
_CLASSIFIABLE_LABELS: list[str] = [
    choice.value for choice in ClauseType if choice != ClauseType.NEEDS_HUMAN_REVIEW
]

_CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "primary_label": {"type": "string", "enum": _CLASSIFIABLE_LABELS},
        "primary_confidence": {"type": "number"},
        "secondary_label": {"type": "string", "enum": _CLASSIFIABLE_LABELS},
        "secondary_confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": [
        "primary_label",
        "primary_confidence",
        "secondary_label",
        "secondary_confidence",
        "rationale",
    ],
    "additionalProperties": False,
}

_CLASSIFICATION_SYSTEM_PROMPT = (
    "You classify one contract clause into exactly one label from this "
    f"fixed taxonomy: {', '.join(_CLASSIFIABLE_LABELS)}. Return your best "
    "label as `primary_label` with `primary_confidence` (0-1), your "
    "second-best label as `secondary_label` with `secondary_confidence`, "
    "and a short `rationale` grounded in the clause text."
)


def classify_clause(*, clause: Clause) -> Clause:
    """Stage 2: assign `clause.clause_type` from the fixed 8-label taxonomy.

    Applies the confidence-threshold (`settings.CLASSIFICATION_MIN_CONFIDENCE`)
    and confidence-margin (`settings.CLASSIFICATION_MIN_MARGIN`) gates,
    overriding the model's label to `needs_human_review` when either gate
    fails - or when the model's proposed label is somehow outside the fixed
    taxonomy, so an out-of-taxonomy value is never persisted. Writes
    exactly one AuditLogEntry (stage=2).

    See specs/pipeline/clause-classification/spec.md.
    """
    started_at = time.monotonic()
    result = llm_client.get_structured_completion(
        _CLASSIFICATION_SYSTEM_PROMPT,
        clause.clause_text,
        _CLASSIFICATION_SCHEMA,
        prompt_version=_CLASSIFICATION_PROMPT_VERSION,
    )
    latency_ms = int((time.monotonic() - started_at) * 1000)

    primary_label = result["primary_label"]
    primary_confidence = float(result["primary_confidence"])
    secondary_confidence = float(result["secondary_confidence"])
    margin = abs(primary_confidence - secondary_confidence)

    below_threshold = primary_confidence < settings.CLASSIFICATION_MIN_CONFIDENCE
    too_close_to_call = margin < settings.CLASSIFICATION_MIN_MARGIN
    out_of_taxonomy = primary_label not in _CLASSIFIABLE_LABELS

    if below_threshold or too_close_to_call or out_of_taxonomy:
        clause_type = ClauseType.NEEDS_HUMAN_REVIEW.value
    else:
        clause_type = primary_label

    clause.clause_type = clause_type
    clause.classification_confidence = primary_confidence
    clause.classification_rationale = result["rationale"]
    clause.save(
        update_fields=["clause_type", "classification_confidence", "classification_rationale"]
    )

    _create_audit_log_entry(
        contract=clause.contract,
        clause=clause,
        stage=PipelineStage.CLASSIFICATION,
        prompt_version=_CLASSIFICATION_PROMPT_VERSION,
        llm_response_raw=result,
        latency_ms=latency_ms,
    )

    return clause


# ---------------------------------------------------------------------------
# Stage 3: term extraction
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT_VERSION = "term-extraction-v1"

# Only these clause types can carry an extractable payment term - see
# specs/pipeline/term-extraction/spec.md (Extraction scoped to
# payment-bearing clause types).
_PAYMENT_BEARING_CLAUSE_TYPES: frozenset[str] = frozenset(
    {
        ClauseType.PAYMENT_SCHEDULE.value,
        ClauseType.PENALTY_LATE_FEE.value,
        ClauseType.AUTO_RENEWAL.value,
    }
)

_TERM_TYPES: list[str] = [choice.value for choice in TermType]

_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term_type": {"type": "string", "enum": _TERM_TYPES},
                    "value_raw": {"type": "string"},
                    "numeric_value": {"type": ["number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "is_formula_based": {"type": "boolean"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "term_type",
                    "value_raw",
                    "numeric_value",
                    "unit",
                    "is_formula_based",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["terms"],
    "additionalProperties": False,
}

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured payment terms explicitly stated in one "
    f"contract clause. Each term's `term_type` is one of: "
    f"{', '.join(_TERM_TYPES)}. `value_raw` MUST be an exact, "
    "character-for-character quote from the clause text supporting the "
    "term. Set `numeric_value` and `unit` only when the clause states an "
    "explicit number - if the clause states the term qualitatively (for "
    'example "within a reasonable time") with no explicit number, leave '
    "`numeric_value` and `unit` null rather than guessing a value. Set "
    "`is_formula_based` to true when the term is stated as a formula this "
    "schema cannot represent as a single number (for example a "
    "compounding percentage) - in that case still set `value_raw` to the "
    "verbatim clause text and leave `numeric_value` null. Never invent a "
    "term that is not explicitly stated in the clause; if nothing "
    "payment-relevant is stated, return an empty `terms` list."
)


def extract_terms(*, clause: Clause) -> list[ExtractedTerm]:
    """Stage 3: extract structured ExtractedTerm rows from a payment-bearing clause.

    No-ops (no model call, no AuditLogEntry) for a clause not classified
    as payment_schedule, penalty_late_fee, or auto_renewal. Otherwise
    writes one ExtractedTerm per term the model reports and exactly one
    AuditLogEntry (stage=3). A term is marked `needs_human_review` when it
    is formula-based, its `value_raw` cannot be found verbatim in the
    clause text, or its confidence falls below
    `settings.EXTRACTION_MIN_CONFIDENCE`.

    See specs/pipeline/term-extraction/spec.md.
    """
    if clause.clause_type not in _PAYMENT_BEARING_CLAUSE_TYPES:
        return []

    started_at = time.monotonic()
    result = llm_client.get_structured_completion(
        _EXTRACTION_SYSTEM_PROMPT,
        clause.clause_text,
        _EXTRACTION_SCHEMA,
        prompt_version=_EXTRACTION_PROMPT_VERSION,
    )
    latency_ms = int((time.monotonic() - started_at) * 1000)

    terms: list[ExtractedTerm] = []
    with transaction.atomic():
        for item in result["terms"]:
            is_formula_based = bool(item["is_formula_based"])
            confidence = float(item["confidence"])
            value_raw = item["value_raw"]
            # A formula-based term can never be represented as a single
            # number - force it null even if the model attempted one,
            # rather than persist a misleading numeric guess.
            numeric_value = None if is_formula_based else item["numeric_value"]

            is_grounded = llm_client.quote_is_verbatim(clause.clause_text, value_raw)
            needs_human_review = (
                is_formula_based
                or not is_grounded
                or confidence < settings.EXTRACTION_MIN_CONFIDENCE
            )

            terms.append(
                ExtractedTerm.objects.create(
                    clause=clause,
                    term_type=item["term_type"],
                    value_raw=value_raw,
                    value_structured={"numeric_value": numeric_value, "unit": item["unit"]},
                    extraction_confidence=confidence,
                    needs_human_review=needs_human_review,
                )
            )

    _create_audit_log_entry(
        contract=clause.contract,
        clause=clause,
        stage=PipelineStage.EXTRACTION,
        prompt_version=_EXTRACTION_PROMPT_VERSION,
        llm_response_raw=result,
        latency_ms=latency_ms,
    )

    return terms


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_VALID_FROM_STAGES = (
    PipelineStage.SEGMENTATION,
    PipelineStage.CLASSIFICATION,
    PipelineStage.EXTRACTION,
)


def run_pipeline(*, contract: Contract, from_stage: int = 1) -> None:
    """Orchestrate stages 1-3 for `contract`, resuming from `from_stage`.

    Each stage function reads/writes only via the database - no Python
    object is threaded between stages - so this can resume at any stage
    using rows a prior call already persisted (e.g. `from_stage=2` after
    stage 1 ran in an earlier invocation, or after per-clause human review
    resubmission from phase 3 onward).

    After stage 3, and unless `settings.ENABLE_STAGE_4` is False, this also
    invokes `razorpay_integration.services.detect_mismatches` (pipeline
    stage 4 - see openspec/changes/add-razorpay-crosscheck/design.md). That
    import is deliberately function-local, not module-level: `pipeline`
    cannot import `razorpay_integration` at module scope because
    `razorpay_integration.services` itself imports `pipeline.selectors`,
    which would be a circular import. By the time `run_pipeline` actually
    runs, both modules have finished loading, so the local import resolves
    cleanly. `detect_mismatches` reads its own inputs from the database via
    selectors - this function passes it only `contract`, never a
    pre-fetched ExtractedTerm, preserving the no-in-memory-handoff rule
    above.

    After stage 4, this also invokes `risk_scoring.services.score_clause`
    (pipeline stage 5 - see
    openspec/changes/add-risk-scoring-report/design.md) once per Clause on
    the contract, unconditionally - unlike stage 4 there is no settings
    flag gating it, since every classified clause (including ones with no
    ExtractedTerm rows at all) must get a RiskAssessment. Following the
    same precedent as the stage-4 import, this import is function-local,
    not module-level, to avoid any import-order coupling between `pipeline`
    and `risk_scoring`. `score_clause` reads its own inputs via selectors -
    this function passes it only `clause`, preserving the
    no-in-memory-handoff rule above.

    Raises:
        ValueError: if `from_stage` is not 1, 2, or 3.
    """
    if from_stage not in _VALID_FROM_STAGES:
        raise ValueError(f"from_stage must be 1, 2, or 3, got {from_stage!r}")

    if from_stage <= PipelineStage.SEGMENTATION:
        segment_contract(contract=contract)

    if from_stage <= PipelineStage.CLASSIFICATION:
        for clause in contracts_selectors.list_clauses_for_contract(contract=contract):
            classify_clause(clause=clause)

    if from_stage <= PipelineStage.EXTRACTION:
        for clause in contracts_selectors.list_clauses_for_contract(contract=contract):
            extract_terms(clause=clause)

    if settings.ENABLE_STAGE_4:
        from razorpay_integration import services as razorpay_integration_services

        razorpay_integration_services.detect_mismatches(contract=contract)

    from risk_scoring import services as risk_scoring_services

    for clause in contracts_selectors.list_clauses_for_contract(contract=contract):
        risk_scoring_services.score_clause(clause=clause)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _create_audit_log_entry(
    *,
    contract: Contract,
    clause: Clause | None,
    stage: int,
    prompt_version: str,
    llm_response_raw: dict[str, Any],
    latency_ms: int,
) -> AuditLogEntry:
    """Persist the one AuditLogEntry every stage invocation writes.

    See specs/pipeline/audit-trail/spec.md (One audit entry per stage
    invocation).
    """
    return AuditLogEntry.objects.create(
        contract=contract,
        clause=clause,
        stage=stage,
        prompt_version=prompt_version,
        llm_response_raw=llm_response_raw,
        model_name=settings.OPENAI_MODEL,
        latency_ms=latency_ms,
    )
