"""Tests for razorpay_integration.selectors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.models import PlatformRecordType
from razorpay_integration.selectors import (
    DAYS_PER_UNIT,
    TIME_UNITS,
    get_latest_payout_records,
    get_platform_records_for_contract,
    is_amount_term,
    is_cadence_term,
    list_mismatch_flags_for_contract,
    term_numeric_value,
    term_unit,
)
from razorpay_integration.tests.factories import MismatchFlagFactory, PlatformRecordFactory

pytestmark = pytest.mark.django_db

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class TestCadenceAmountClassification:
    """Promoted (public) from razorpay_integration.services in
    add-overdue-payment-detection - see that change's design.md (Decision 2).
    Behavior is unchanged from the private helpers these replace; this is
    direct coverage for the now-public names, previously only exercised
    indirectly through `_run_payout_crosscheck`/`_run_subscription_crosscheck`.
    """

    def test_time_units_and_days_per_unit_agree_on_key_set(self):
        assert set(TIME_UNITS) == set(DAYS_PER_UNIT)

    def test_term_unit_lowercases_and_strips(self):
        term = ExtractedTermFactory.build(value_structured={"numeric_value": 30, "unit": " Days "})
        assert term_unit(term) == "days"

    def test_term_unit_none_when_missing_or_blank(self):
        assert term_unit(ExtractedTermFactory.build(value_structured={})) is None
        assert term_unit(ExtractedTermFactory.build(value_structured={"unit": "  "})) is None

    def test_term_numeric_value_coerces_to_float(self):
        term = ExtractedTermFactory.build(value_structured={"numeric_value": 30, "unit": "days"})
        assert term_numeric_value(term) == 30.0

    def test_term_numeric_value_none_when_missing(self):
        assert term_numeric_value(ExtractedTermFactory.build(value_structured={})) is None

    def test_is_cadence_term_true_for_recognized_time_unit(self):
        term = ExtractedTermFactory.build(value_structured={"numeric_value": 30, "unit": "days"})
        assert is_cadence_term(term) is True
        assert is_amount_term(term) is False

    def test_is_amount_term_true_for_non_time_unit(self):
        term = ExtractedTermFactory.build(value_structured={"numeric_value": 500, "unit": "INR"})
        assert is_amount_term(term) is True
        assert is_cadence_term(term) is False

    def test_neither_cadence_nor_amount_when_no_numeric_value(self):
        term = ExtractedTermFactory.build(value_structured={"unit": "days"})
        # A unit alone with no numeric_value is still cadence-shaped by unit
        # name, but is_amount_term requires a numeric_value.
        assert is_cadence_term(term) is True
        assert is_amount_term(term) is False
        term_no_value_no_unit = ExtractedTermFactory.build(value_structured={})
        assert is_cadence_term(term_no_value_no_unit) is False
        assert is_amount_term(term_no_value_no_unit) is False


class TestGetPlatformRecordsForContract:
    def test_returns_records_for_the_given_contract_only(self):
        contract_a = ContractFactory()
        contract_b = ContractFactory()
        record_a = PlatformRecordFactory(contract=contract_a)
        record_b = PlatformRecordFactory(contract=contract_b)

        records = list(get_platform_records_for_contract(contract=contract_a))

        assert record_a in records
        assert record_b not in records

    def test_filters_by_record_type(self):
        contract = ContractFactory()
        payout = PlatformRecordFactory(contract=contract, record_type=PlatformRecordType.PAYOUT)
        subscription = PlatformRecordFactory(
            contract=contract, record_type=PlatformRecordType.SUBSCRIPTION
        )

        records = list(
            get_platform_records_for_contract(
                contract=contract, record_type=PlatformRecordType.PAYOUT
            )
        )

        assert payout in records
        assert subscription not in records

    def test_ordered_by_razorpay_created_at(self):
        contract = ContractFactory()
        later = PlatformRecordFactory(
            contract=contract, razorpay_created_at=_EPOCH + timedelta(days=5)
        )
        earlier = PlatformRecordFactory(contract=contract, razorpay_created_at=_EPOCH)

        records = list(get_platform_records_for_contract(contract=contract))

        assert [r.id for r in records] == [earlier.id, later.id]

    def test_empty_for_contract_with_no_platform_records(self):
        contract = ContractFactory()

        assert list(get_platform_records_for_contract(contract=contract)) == []


class TestListMismatchFlagsForContract:
    def test_returns_flags_traceable_to_the_given_contract(self):
        contract_a = ContractFactory()
        contract_b = ContractFactory()
        clause_a = ClauseFactory(contract=contract_a)
        clause_b = ClauseFactory(contract=contract_b)
        term_a = ExtractedTermFactory(clause=clause_a)
        term_b = ExtractedTermFactory(clause=clause_b)
        flag_a = MismatchFlagFactory(extracted_term=term_a)
        flag_b = MismatchFlagFactory(extracted_term=term_b)

        flags = list(list_mismatch_flags_for_contract(contract=contract_a))

        assert flag_a in flags
        assert flag_b not in flags

    def test_empty_for_contract_with_no_mismatch_flags(self):
        contract = ContractFactory()

        assert list(list_mismatch_flags_for_contract(contract=contract)) == []


class TestGetLatestPayoutRecords:
    def test_returns_empty_queryset_when_fewer_than_minimum(self):
        contract = ContractFactory()
        PlatformRecordFactory(contract=contract, record_type=PlatformRecordType.PAYOUT)

        records = get_latest_payout_records(contract=contract, minimum=2)

        assert list(records) == []

    def test_returns_records_when_minimum_satisfied(self):
        contract = ContractFactory()
        first = PlatformRecordFactory(
            contract=contract, record_type=PlatformRecordType.PAYOUT, razorpay_created_at=_EPOCH
        )
        second = PlatformRecordFactory(
            contract=contract,
            record_type=PlatformRecordType.PAYOUT,
            razorpay_created_at=_EPOCH + timedelta(days=30),
        )

        records = list(get_latest_payout_records(contract=contract, minimum=2))

        assert {r.id for r in records} == {first.id, second.id}

    def test_ignores_non_payout_records_when_counting(self):
        contract = ContractFactory()
        PlatformRecordFactory(contract=contract, record_type=PlatformRecordType.PAYOUT)
        PlatformRecordFactory(contract=contract, record_type=PlatformRecordType.SUBSCRIPTION)
        PlatformRecordFactory(contract=contract, record_type=PlatformRecordType.TOKEN)

        records = get_latest_payout_records(contract=contract, minimum=2)

        assert list(records) == []
