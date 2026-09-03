import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

# Re-exported so `razorpay_integration` tests can build a Contract/Clause/
# ExtractedTerm without depending on other apps' test paths directly -
# `contracts`/`pipeline` factories are the single source of truth for those
# models.
from contracts.tests.factories import ClauseFactory, ContractFactory  # noqa: F401
from pipeline.tests.factories import ExtractedTermFactory  # noqa: F401
from razorpay_integration.models import (
    MismatchFlag,
    MismatchType,
    PlatformRecord,
    PlatformRecordType,
)


class PlatformRecordFactory(DjangoModelFactory):
    class Meta:
        model = PlatformRecord

    contract = factory.SubFactory(ContractFactory)
    record_type = PlatformRecordType.PAYOUT
    razorpay_id = factory.Sequence(lambda n: f"pout_{n:06d}")
    payload = factory.LazyFunction(lambda: {"id": "pout_000000", "amount": 500000})
    razorpay_created_at = factory.LazyFunction(timezone.now)


class MismatchFlagFactory(DjangoModelFactory):
    class Meta:
        model = MismatchFlag

    extracted_term = factory.SubFactory(ExtractedTermFactory)
    platform_record = factory.SubFactory(PlatformRecordFactory)
    mismatch_type = MismatchType.CADENCE_MISMATCH
    expected_value = factory.LazyFunction(lambda: {"numeric_value": 30, "unit": "days"})
    actual_value = factory.LazyFunction(lambda: {"empirical_cadence_days": 45.0})
    description = "Contract states a 30-day cadence but the observed cadence is 45 days."
