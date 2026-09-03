"""Tests for razorpay_integration.models.

Spec: design.md (add-razorpay-crosscheck) - Decisions (PlatformRecord,
MismatchFlag field definitions).
"""

import pytest

from razorpay_integration.models import (
    MismatchFlag,
    MismatchType,
    PlatformRecord,
    PlatformRecordType,
)
from razorpay_integration.tests.factories import (
    ExtractedTermFactory,
    MismatchFlagFactory,
    PlatformRecordFactory,
)

pytestmark = pytest.mark.django_db


class TestPlatformRecord:
    @pytest.mark.parametrize(
        "record_type",
        [PlatformRecordType.PAYOUT, PlatformRecordType.SUBSCRIPTION, PlatformRecordType.TOKEN],
    )
    def test_creates_one_instance_per_record_type(self, record_type):
        record = PlatformRecordFactory(record_type=record_type)

        reloaded = PlatformRecord.objects.get(id=record.id)
        assert reloaded.record_type == record_type
        assert reloaded.payload == record.payload
        assert reloaded.fetched_at is not None


class TestMismatchFlag:
    @pytest.mark.parametrize(
        "mismatch_type",
        [
            MismatchType.CADENCE_MISMATCH,
            MismatchType.AMOUNT_MISMATCH,
            MismatchType.MISSING_PLATFORM_EVIDENCE,
            MismatchType.TRIGGER_CONDITION_UNVERIFIABLE,
        ],
    )
    def test_creates_one_instance_per_mismatch_type(self, mismatch_type):
        flag = MismatchFlagFactory(mismatch_type=mismatch_type)

        reloaded = MismatchFlag.objects.get(id=flag.id)
        assert reloaded.mismatch_type == mismatch_type
        assert reloaded.extracted_term_id == flag.extracted_term_id

    def test_platform_record_nullable(self):
        term = ExtractedTermFactory()
        flag = MismatchFlagFactory(
            extracted_term=term,
            platform_record=None,
            mismatch_type=MismatchType.MISSING_PLATFORM_EVIDENCE,
        )

        reloaded = MismatchFlag.objects.get(id=flag.id)
        assert reloaded.platform_record is None
