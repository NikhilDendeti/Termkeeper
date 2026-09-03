"""Models for the `pipeline` app.

`pipeline` owns the entities that only exist because AI processing ran
against a Contract/Clause from `contracts`: the structured terms an
extraction call produced (`ExtractedTerm`) and the audit record of every
stage invocation (`AuditLogEntry`). See design.md (add-django-foundation)
for the app-boundary rationale.
"""

import uuid

from django.db import models

from contracts.models import Clause, Contract


class TermType(models.TextChoices):
    """Fixed 5-type taxonomy of payment terms a payment-bearing clause can yield.

    See proposal.md ("payout frequency, milestone trigger, penalty amount,
    notice period, auto-renewal terms") and
    specs/pipeline/term-extraction/spec.md.
    """

    PAYOUT_FREQUENCY = "payout_frequency", "Payout frequency"
    MILESTONE_TRIGGER = "milestone_trigger", "Milestone trigger"
    PENALTY_AMOUNT = "penalty_amount", "Penalty amount"
    NOTICE_PERIOD = "notice_period", "Notice period"
    AUTO_RENEWAL_TERM = "auto_renewal_term", "Auto-renewal term"


class PipelineStage(models.IntegerChoices):
    """The three pipeline stages this phase implements, in run order."""

    SEGMENTATION = 1, "Segmentation"
    CLASSIFICATION = 2, "Classification"
    EXTRACTION = 3, "Extraction"


class ExtractedTerm(models.Model):
    """One structured payment term pulled from a payment-bearing Clause.

    `value_raw` is the verbatim clause-text span the value was read from
    (validated against `clause.clause_text` before this row is written);
    `value_structured` holds the parsed `numeric_value`/`unit` pair, with
    `numeric_value` left `None` whenever the clause states the term
    qualitatively rather than numerically, per
    specs/pipeline/term-extraction/spec.md.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clause = models.ForeignKey(Clause, on_delete=models.CASCADE, related_name="extracted_terms")
    term_type = models.CharField(max_length=32, choices=TermType.choices)
    value_raw = models.TextField()
    value_structured = models.JSONField(default=dict)
    extraction_confidence = models.FloatField()
    needs_human_review = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.term_type} for clause {self.clause_id}"


class AuditLogEntry(models.Model):
    """One persisted record of a single pipeline-stage invocation.

    `clause` is null for a contract-level invocation (stage 1, segmentation
    is not scoped to a single clause) and set for a clause-level invocation
    (stages 2 and 3). See specs/pipeline/audit-trail/spec.md.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name="audit_log_entries"
    )
    clause = models.ForeignKey(
        Clause,
        on_delete=models.CASCADE,
        related_name="audit_log_entries",
        null=True,
        blank=True,
    )
    stage = models.PositiveSmallIntegerField(choices=PipelineStage.choices)
    prompt_version = models.CharField(max_length=64)
    llm_response_raw = models.JSONField()
    model_name = models.CharField(max_length=128)
    latency_ms = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["stage", "created_at"]
        verbose_name_plural = "audit log entries"

    def __str__(self) -> str:
        return f"AuditLogEntry stage={self.stage} contract={self.contract_id}"
