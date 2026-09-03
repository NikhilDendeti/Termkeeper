import uuid

from django.db import models


class RazorpayReferenceType(models.TextChoices):
    """The two kinds of live Razorpay resource a Contract can be cross-checked against."""

    PAYOUT = "payout", "Payout"
    SUBSCRIPTION = "subscription", "Subscription"


class ClauseType(models.TextChoices):
    """Fixed 8-label clause-type taxonomy.

    Defined here (not in `pipeline`) because `Clause` lives in `contracts`.
    `pipeline` imports and reuses this — it is not duplicated there.
    See openspec/changes/add-django-foundation/specs/pipeline/clause-classification/spec.md.
    """

    PAYMENT_SCHEDULE = "payment_schedule", "Payment schedule"
    TERMINATION = "termination", "Termination"
    PENALTY_LATE_FEE = "penalty_late_fee", "Penalty / late fee"
    DISPUTE_RESOLUTION = "dispute_resolution", "Dispute resolution"
    AUTO_RENEWAL = "auto_renewal", "Auto-renewal"
    INDEMNITY = "indemnity", "Indemnity"
    OTHER = "other", "Other"
    NEEDS_HUMAN_REVIEW = "needs_human_review", "Needs human review"


class Contract(models.Model):
    """A contract's raw text plus the engagement/Razorpay metadata it was submitted with."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement_id = models.CharField(max_length=255)
    raw_text = models.TextField()
    source_filename = models.CharField(max_length=255, null=True, blank=True)
    razorpay_reference_type = models.CharField(
        max_length=32, choices=RazorpayReferenceType.choices
    )
    razorpay_reference_id = models.CharField(max_length=255)
    needs_human_review = models.BooleanField(default=False)
    human_review_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Contract {self.id} ({self.engagement_id})"


class Clause(models.Model):
    """One verbatim, position-tracked span of a Contract's raw text."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="clauses")
    sequence_index = models.PositiveIntegerField()
    clause_text = models.TextField()
    clause_type = models.CharField(
        max_length=32, choices=ClauseType.choices, null=True, blank=True
    )
    classification_confidence = models.FloatField(null=True, blank=True)
    classification_rationale = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "sequence_index"],
                name="unique_clause_sequence_per_contract",
            )
        ]

    def __str__(self) -> str:
        return f"Clause {self.sequence_index} of {self.contract_id}"
