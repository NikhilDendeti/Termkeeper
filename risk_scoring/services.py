"""Write-path service functions for the `risk_scoring` app.

This app implements pipeline stage 5: scoring every classified Clause for
severity and directional asymmetry. Every write (`RiskAssessment`) goes
through a function here; `AuditLogEntry` writes route through the one
shared `pipeline.services.create_audit_log_entry` - see
openspec/changes/add-audit-log-hash-chain/design.md (this app no longer
defines its own `_create_audit_log_entry`). `score_clause` reads its
inputs via selectors (this app's own and `risk_scoring.selectors`), never
via an in-process value handed from an earlier pipeline stage - the same
no-in-memory-handoff rule phase 1 established for stages 1-3 and phase 2
continued for stage 4. See design.md (add-risk-scoring-report) - Context and
Decisions.

Severity is always computed in Python from a bounded LLM output
(`asymmetry_score`), never named by the LLM directly - see design.md -
Decisions ("Severity is computed in Python from a bounded LLM output, never
named by the LLM directly").
"""

from __future__ import annotations

import time
from typing import Any

from django.conf import settings

from contracts.models import Clause, ClauseType
from core import llm_client
from pipeline import services as pipeline_services
from risk_scoring import selectors as risk_scoring_selectors
from risk_scoring.models import RiskAssessment, SeverityChoices

# AuditLogEntry.stage is an unconstrained PositiveSmallIntegerField (choices
# are not DB-enforced) - stage 5 is additive by construction and requires no
# change to pipeline.models.PipelineStage (which only defines stages 1-3),
# mirroring razorpay_integration's own `_STAGE_4 = 4` precedent. See
# proposal.md - Impact.
_STAGE_5 = 5

# ---------------------------------------------------------------------------
# Deterministic severity formula
# ---------------------------------------------------------------------------

# Fixed per-clause-type criticality weight - see design.md - Decisions
# ("Severity is computed in Python from a bounded LLM output..."), step 1.
CRITICALITY_WEIGHTS: dict[str, float] = {
    ClauseType.PAYMENT_SCHEDULE.value: 1.0,
    ClauseType.PENALTY_LATE_FEE.value: 1.0,
    ClauseType.TERMINATION.value: 0.8,
    ClauseType.INDEMNITY.value: 0.8,
    ClauseType.AUTO_RENEWAL.value: 0.6,
    ClauseType.DISPUTE_RESOLUTION.value: 0.5,
    ClauseType.OTHER.value: 0.3,
}

_MISMATCH_BUMP = 0.25

_ACTIONABLE_SEVERITIES: frozenset[str] = frozenset(
    {SeverityChoices.MEDIUM.value, SeverityChoices.HIGH.value, SeverityChoices.CRITICAL.value}
)


def _compute_severity(*, clause_type: str, asymmetry_score: float, has_mismatch: bool) -> str:
    """Deterministically band a clause's severity from asymmetry/criticality/mismatch.

    1. `criticality = CRITICALITY_WEIGHTS[clause_type]`.
    2. `base = abs(asymmetry_score) * criticality` (range [0, 1]).
    3. `bumped = min(base + 0.25, 1.0)` if a MismatchFlag is linked, else `base`.
    4. Band: >=0.75 critical, >=0.5 high, >=0.25 medium, else low.

    See design.md - Decisions (same section) and
    specs/risk-scoring/clause-severity/spec.md (Requirement: Severity
    determined by asymmetry, clause-type criticality, and mismatch linkage).
    """
    criticality = CRITICALITY_WEIGHTS[clause_type]
    base = min(abs(asymmetry_score) * criticality, 1.0)
    bumped = min(base + _MISMATCH_BUMP, 1.0) if has_mismatch else base

    if bumped >= 0.75:
        return SeverityChoices.CRITICAL.value
    if bumped >= 0.5:
        return SeverityChoices.HIGH.value
    if bumped >= 0.25:
        return SeverityChoices.MEDIUM.value
    return SeverityChoices.LOW.value


# ---------------------------------------------------------------------------
# Stage 5: quote-grounded severity/asymmetry scoring
# ---------------------------------------------------------------------------

_RISK_SCORING_PROMPT_VERSION = "clause-risk-scoring-v1"
_RISK_SCORING_MAX_ATTEMPTS = 2

_RISK_SCORING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["text", "quote"],
                "additionalProperties": False,
            },
        },
        "asymmetry_score": {"type": "number", "minimum": -1, "maximum": 1},
        "suggested_rewrite": {"type": ["string", "null"]},
    },
    "required": ["sentences", "asymmetry_score", "suggested_rewrite"],
    "additionalProperties": False,
}

_RISK_SCORING_SYSTEM_PROMPT = (
    "You assess the risk one contract clause poses to the vendor party. "
    "Write your explanation as `sentences`, a list of objects each with a "
    "`text` field (one explanatory sentence) and a `quote` field. `quote` "
    "MUST be an exact, character-for-character substring copied from the "
    "clause text given - do not paraphrase or compose it. Set "
    "`asymmetry_score` to a number from -1 to 1 measuring how one-sided "
    "the clause's obligation, penalty, or notice burden is: negative "
    "values mean the burden favors the counterparty over the vendor, "
    "positive values mean it favors the vendor, and the magnitude reflects "
    "how one-sided the burden is; 0 means the clause is balanced. Set "
    "`suggested_rewrite` to a fairer alternative wording of the clause "
    "when it is meaningfully one-sided, or null when it is not."
)

# Fixed, system-authored explanations - never model output - used whenever
# no verified LLM explanation can be persisted. See design.md - Decisions
# ("Quote-grounding schema and retry", "needs_human_review inheritance
# short-circuits before any LLM call").
_SHORT_CIRCUIT_EXPLANATION = (
    "clause was not confidently classified; scoring deferred to human review"
)
_UNVERIFIED_EXPLANATION_FALLBACK = (
    "the generated risk explanation could not be verified against the "
    "clause's own text after one retry; scoring deferred to human review"
)


def score_clause(*, clause: Clause) -> RiskAssessment:
    """Stage 5: score a single Clause for severity and directional asymmetry.

    Short-circuits (no model call) to severity=needs_human_review when
    `clause.clause_type` is `needs_human_review` or unset - inheriting that
    state directly from phase 1 classification. Otherwise calls the model for
    a quote-grounded explanation and a bounded `asymmetry_score`, retrying
    once if any sentence's quote fails `core.llm_client.quote_is_verbatim`;
    if the retry also fails, forces severity to needs_human_review instead
    of persisting an unverified explanation. Writes exactly one
    AuditLogEntry (stage=5) per call, and update-or-creates the Clause's
    one current RiskAssessment.

    See specs/risk-scoring/clause-severity/spec.md.
    """
    linked_flag_ids = [
        str(flag.id)
        for flag in risk_scoring_selectors.get_linked_mismatch_flags(clause=clause)
    ]

    if clause.clause_type is None or clause.clause_type == ClauseType.NEEDS_HUMAN_REVIEW.value:
        pipeline_services.create_audit_log_entry(
            contract=clause.contract,
            clause=clause,
            stage=_STAGE_5,
            prompt_version=_RISK_SCORING_PROMPT_VERSION,
            llm_response_raw={
                "short_circuited": True,
                "reason": "clause_type is needs_human_review or unset; scoring LLM not called",
                "clause_type": clause.clause_type,
            },
            model_name=settings.OPENAI_MODEL,
            latency_ms=0,
        )
        return _persist_risk_assessment(
            clause=clause,
            severity=SeverityChoices.NEEDS_HUMAN_REVIEW.value,
            asymmetry_score=0.0,
            explanation=_SHORT_CIRCUIT_EXPLANATION,
            suggested_rewrite=None,
            linked_mismatch_flag_ids=linked_flag_ids,
        )

    result: dict[str, Any] = {}
    sentences: list[dict[str, Any]] = []
    total_latency_ms = 0
    verified = False

    for _attempt in range(_RISK_SCORING_MAX_ATTEMPTS):
        started_at = time.monotonic()
        result = llm_client.get_structured_completion(
            _RISK_SCORING_SYSTEM_PROMPT,
            clause.clause_text,
            _RISK_SCORING_SCHEMA,
            prompt_version=_RISK_SCORING_PROMPT_VERSION,
        )
        total_latency_ms += int((time.monotonic() - started_at) * 1000)

        sentences = result["sentences"]
        verified = bool(sentences) and all(
            llm_client.quote_is_verbatim(clause.clause_text, item["quote"])
            for item in sentences
        )
        if verified:
            break

    pipeline_services.create_audit_log_entry(
        contract=clause.contract,
        clause=clause,
        stage=_STAGE_5,
        prompt_version=_RISK_SCORING_PROMPT_VERSION,
        llm_response_raw=result,
        model_name=settings.OPENAI_MODEL,
        latency_ms=total_latency_ms,
    )

    has_mismatch = bool(linked_flag_ids)

    if not verified:
        return _persist_risk_assessment(
            clause=clause,
            severity=SeverityChoices.NEEDS_HUMAN_REVIEW.value,
            asymmetry_score=0.0,
            explanation=_UNVERIFIED_EXPLANATION_FALLBACK,
            suggested_rewrite=None,
            linked_mismatch_flag_ids=linked_flag_ids,
        )

    asymmetry_score = float(result["asymmetry_score"])
    severity = _compute_severity(
        clause_type=clause.clause_type,
        asymmetry_score=asymmetry_score,
        has_mismatch=has_mismatch,
    )
    explanation = " ".join(item["text"] for item in sentences)
    suggested_rewrite = (
        result.get("suggested_rewrite") if severity in _ACTIONABLE_SEVERITIES else None
    )

    return _persist_risk_assessment(
        clause=clause,
        severity=severity,
        asymmetry_score=asymmetry_score,
        explanation=explanation,
        suggested_rewrite=suggested_rewrite,
        linked_mismatch_flag_ids=linked_flag_ids,
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _persist_risk_assessment(
    *,
    clause: Clause,
    severity: str,
    asymmetry_score: float,
    explanation: str,
    suggested_rewrite: str | None,
    linked_mismatch_flag_ids: list[str],
) -> RiskAssessment:
    """Update-or-create the Clause's one current RiskAssessment.

    `clause.risk_assessment` is a `OneToOneField` - re-running stage 5 for a
    clause replaces its current row rather than appending a new one. See
    design.md - Decisions ("RiskAssessment.clause is a OneToOneField, not a
    plain ForeignKey").
    """
    assessment, _created = RiskAssessment.objects.update_or_create(
        clause=clause,
        defaults={
            "severity": severity,
            "asymmetry_score": asymmetry_score,
            "explanation": explanation,
            "suggested_rewrite": suggested_rewrite,
            "linked_mismatch_flag_ids": linked_mismatch_flag_ids,
        },
    )
    return assessment
