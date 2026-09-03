"""Write-path service functions for the `contracts` app.

Every write to a Contract/Clause goes through a function here — per project
convention, views/management commands never write to models directly.
"""

from django.core.exceptions import ValidationError

from contracts.models import Contract


def create_contract(
    *,
    raw_text: str,
    engagement_id: str,
    razorpay_reference_type: str,
    razorpay_reference_id: str,
    source_filename: str | None = None,
) -> Contract:
    """Persist a contract's raw text and engagement/Razorpay metadata.

    See openspec/changes/add-django-foundation/specs/contracts/ingestion/spec.md
    (Requirement: Contract creation from raw text).

    Raises:
        ValidationError: if raw_text is empty, or razorpay_reference_type /
            razorpay_reference_id is missing (spec scenario: Missing razorpay
            reference rejected).
    """
    if not raw_text or not raw_text.strip():
        raise ValidationError({"raw_text": "raw_text must not be empty."})
    if not engagement_id or not engagement_id.strip():
        raise ValidationError({"engagement_id": "engagement_id is required."})
    if not razorpay_reference_type:
        raise ValidationError(
            {"razorpay_reference_type": "razorpay_reference_type is required."}
        )
    if not razorpay_reference_id or not razorpay_reference_id.strip():
        raise ValidationError(
            {"razorpay_reference_id": "razorpay_reference_id is required."}
        )

    contract = Contract(
        raw_text=raw_text,
        engagement_id=engagement_id,
        razorpay_reference_type=razorpay_reference_type,
        razorpay_reference_id=razorpay_reference_id,
        source_filename=source_filename,
    )
    contract.full_clean()
    contract.save()
    return contract


def mark_contract_needs_human_review(*, contract: Contract, reason: str) -> Contract:
    """Flag a Contract as needing human review (e.g. on stage-1 segmentation failure)."""
    contract.needs_human_review = True
    contract.human_review_reason = reason
    contract.save(update_fields=["needs_human_review", "human_review_reason", "updated_at"])
    return contract
