"""Models for the `razorpay_integration` app.

`razorpay_integration` owns the entities produced by pipeline stage 4: the
raw evidence pulled from Razorpay (`PlatformRecord`) and the mismatches
detected by comparing that evidence against phase 1's `ExtractedTerm` rows
(`MismatchFlag`). Fields/constraints/simple validation only, per HackSoft
convention - no business logic on the model. See design.md
(add-razorpay-crosscheck) - Decisions.
"""

import uuid

from django.db import models

from contracts.models import Contract
from pipeline.models import ExtractedTerm


class PlatformRecordType(models.TextChoices):
    """The three kinds of raw Razorpay resource this app fetches via GET."""

    PAYOUT = "payout", "Payout"
    SUBSCRIPTION = "subscription", "Subscription"
    TOKEN = "token", "Token"


class MismatchType(models.TextChoices):
    """Fixed 4-label mismatch taxonomy.

    See specs/razorpay-integration/mismatch-flagging/spec.md (Requirement:
    Mismatch type restricted to a fixed taxonomy).
    """

    CADENCE_MISMATCH = "cadence_mismatch", "Cadence mismatch"
    AMOUNT_MISMATCH = "amount_mismatch", "Amount mismatch"
    MISSING_PLATFORM_EVIDENCE = "missing_platform_evidence", "Missing platform evidence"
    TRIGGER_CONDITION_UNVERIFIABLE = (
        "trigger_condition_unverifiable",
        "Trigger condition unverifiable",
    )


class PlatformRecord(models.Model):
    """One raw GET response fetched from Razorpay (payout, subscription, or token).

    `payload` keeps the full API response verbatim, independent of whatever
    fields the comparison logic reads - mirrors phase 1's
    `AuditLogEntry.llm_response_raw` pattern (see design.md - "PlatformRecord
    stores the raw payload").
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name="platform_records"
    )
    record_type = models.CharField(max_length=32, choices=PlatformRecordType.choices)
    razorpay_id = models.CharField(max_length=255)
    payload = models.JSONField()
    razorpay_created_at = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["razorpay_created_at"]

    def __str__(self) -> str:
        return f"{self.record_type} {self.razorpay_id} for contract {self.contract_id}"


class MismatchFlag(models.Model):
    """One detected mismatch between a contract-stated term and platform evidence.

    `platform_record` is null only for a missing_platform_evidence or
    trigger_condition_unverifiable mismatch - see
    specs/razorpay-integration/mismatch-flagging/spec.md (Requirement:
    Persisted MismatchFlag links term and platform evidence).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    extracted_term = models.ForeignKey(
        ExtractedTerm, on_delete=models.CASCADE, related_name="mismatch_flags"
    )
    platform_record = models.ForeignKey(
        PlatformRecord,
        on_delete=models.CASCADE,
        related_name="mismatch_flags",
        null=True,
        blank=True,
    )
    mismatch_type = models.CharField(max_length=32, choices=MismatchType.choices)
    expected_value = models.JSONField()
    actual_value = models.JSONField()
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.mismatch_type} for term {self.extracted_term_id}"
