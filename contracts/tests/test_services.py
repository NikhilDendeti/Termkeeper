import pytest
from django.core.exceptions import ValidationError

from contracts.models import Contract
from contracts.services import create_contract, mark_contract_needs_human_review
from contracts.tests.factories import ContractFactory

pytestmark = pytest.mark.django_db


class TestCreateContract:
    """Spec: contracts/ingestion - Requirement: Contract creation from raw text."""

    def test_valid_contract_submitted_creates_contract_and_returns_identifier(self):
        # Scenario: Valid contract submitted
        contract = create_contract(
            raw_text="This agreement shall govern payment terms between the parties.",
            engagement_id="ENG-001",
            razorpay_reference_type="payout",
            razorpay_reference_id="pout_ABC123",
            source_filename="msa.txt",
        )

        assert contract.id is not None
        assert Contract.objects.filter(id=contract.id).exists()
        stored = Contract.objects.get(id=contract.id)
        assert stored.engagement_id == "ENG-001"
        assert stored.raw_text == "This agreement shall govern payment terms between the parties."
        assert stored.razorpay_reference_type == "payout"
        assert stored.razorpay_reference_id == "pout_ABC123"
        assert stored.source_filename == "msa.txt"

    def test_valid_contract_with_subscription_reference_type(self):
        contract = create_contract(
            raw_text="Subscription terms apply.",
            engagement_id="ENG-002",
            razorpay_reference_type="subscription",
            razorpay_reference_id="sub_XYZ789",
        )

        assert contract.razorpay_reference_type == "subscription"

    def test_missing_razorpay_reference_type_rejected(self):
        # Scenario: Missing razorpay reference rejected
        with pytest.raises(ValidationError) as exc_info:
            create_contract(
                raw_text="Some contract text.",
                engagement_id="ENG-003",
                razorpay_reference_type="",
                razorpay_reference_id="pout_ABC123",
            )

        assert "razorpay_reference_type" in exc_info.value.message_dict

    def test_missing_razorpay_reference_id_rejected(self):
        # Scenario: Missing razorpay reference rejected
        with pytest.raises(ValidationError) as exc_info:
            create_contract(
                raw_text="Some contract text.",
                engagement_id="ENG-004",
                razorpay_reference_type="payout",
                razorpay_reference_id="",
            )

        assert "razorpay_reference_id" in exc_info.value.message_dict

    def test_invalid_razorpay_reference_type_value_rejected(self):
        with pytest.raises(ValidationError):
            create_contract(
                raw_text="Some contract text.",
                engagement_id="ENG-005",
                razorpay_reference_type="not_a_real_type",
                razorpay_reference_id="pout_ABC123",
            )

    def test_empty_raw_text_rejected(self):
        with pytest.raises(ValidationError):
            create_contract(
                raw_text="   ",
                engagement_id="ENG-006",
                razorpay_reference_type="payout",
                razorpay_reference_id="pout_ABC123",
            )

    def test_rejected_submission_persists_nothing(self):
        before = Contract.objects.count()
        with pytest.raises(ValidationError):
            create_contract(
                raw_text="Some contract text.",
                engagement_id="ENG-007",
                razorpay_reference_type="payout",
                razorpay_reference_id="",
            )
        assert Contract.objects.count() == before


class TestEngagementTraceability:
    """Spec: contracts/ingestion - Requirement: Engagement traceability."""

    def test_reference_resolvable_after_creation(self):
        contract = create_contract(
            raw_text="Payment terms text.",
            engagement_id="ENG-100",
            razorpay_reference_type="subscription",
            razorpay_reference_id="sub_111",
        )

        reloaded = Contract.objects.get(id=contract.id)
        assert reloaded.engagement_id == "ENG-100"
        assert reloaded.razorpay_reference_type == "subscription"
        assert reloaded.razorpay_reference_id == "sub_111"


class TestMarkContractNeedsHumanReview:
    def test_marks_contract_and_records_reason(self):
        contract = ContractFactory(needs_human_review=False)

        updated = mark_contract_needs_human_review(
            contract=contract, reason="Segmentation validation failed twice."
        )

        assert updated.needs_human_review is True
        assert updated.human_review_reason == "Segmentation validation failed twice."

        reloaded = Contract.objects.get(id=contract.id)
        assert reloaded.needs_human_review is True
        assert reloaded.human_review_reason == "Segmentation validation failed twice."
