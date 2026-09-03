"""Tests for the primary (payout-history) cross-check path.

Spec: specs/razorpay-integration/payout-history-crosscheck/spec.md.
Every RazorpayConnector call and every core.llm_client call is mocked -
no real network call is made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings

from contracts.models import RazorpayReferenceType
from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.models import TermType
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.models import (
    MismatchFlag,
    MismatchType,
    PlatformRecord,
    PlatformRecordType,
)
from razorpay_integration.services import (
    _compute_empirical_amount,
    _compute_empirical_cadence_days,
    _run_payout_crosscheck,
    fetch_payout_history,
)
from razorpay_integration.tests.factories import PlatformRecordFactory

pytestmark = pytest.mark.django_db

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def _epoch_ts(days_offset: float) -> int:
    return int((_EPOCH + timedelta(days=days_offset)).timestamp())


def _payout_item(*, id_: str, amount_paise: int, days_offset: float) -> dict:
    return {
        "id": id_,
        "entity": "payout",
        "amount": amount_paise,
        "currency": "INR",
        "status": "processed",
        "created_at": _epoch_ts(days_offset),
    }


def _cadence_term(*, numeric_value: float, unit: str, contract=None):
    clause = ClauseFactory(contract=contract) if contract else ClauseFactory()
    return ExtractedTermFactory(
        clause=clause,
        term_type=TermType.PAYOUT_FREQUENCY,
        value_raw=f"paid every {numeric_value} {unit}",
        value_structured={"numeric_value": numeric_value, "unit": unit},
    )


def _amount_term(*, numeric_value: float, contract=None):
    clause = ClauseFactory(contract=contract) if contract else ClauseFactory()
    return ExtractedTermFactory(
        clause=clause,
        term_type=TermType.PAYOUT_FREQUENCY,
        value_raw=f"an amount of {numeric_value}",
        value_structured={"numeric_value": numeric_value, "unit": "INR"},
    )


class TestFetchPayoutHistory:
    """Requirement: Empirical cadence/amount derivation depends on persisted evidence."""

    def test_two_or_more_payouts_produce_matching_platform_records(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        items = [
            _payout_item(id_="pout_1", amount_paise=500000, days_offset=0),
            _payout_item(id_="pout_2", amount_paise=500000, days_offset=30),
            _payout_item(id_="pout_3", amount_paise=500000, days_offset=60),
        ]
        fake_connector = _FakeConnector(payouts_response={"items": items})

        with patch("razorpay_integration.services.RazorpayConnector", return_value=fake_connector):
            records = fetch_payout_history(contract=contract)

        assert len(records) == 3
        stored = list(PlatformRecord.objects.filter(contract=contract))
        assert len(stored) == 3
        assert all(record.record_type == PlatformRecordType.PAYOUT for record in stored)
        assert {record.razorpay_id for record in stored} == {"pout_1", "pout_2", "pout_3"}
        matching = PlatformRecord.objects.get(razorpay_id="pout_1")
        assert matching.payload == items[0]

    def test_noop_for_a_subscription_referenced_contract(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        item = _payout_item(id_="pout_1", amount_paise=1, days_offset=0)
        fake_connector = _FakeConnector(payouts_response={"items": [item]})

        with patch(
            "razorpay_integration.services.RazorpayConnector", return_value=fake_connector
        ) as mock_connector_cls:
            records = fetch_payout_history(contract=contract)

        mock_connector_cls.assert_not_called()
        assert records == []
        assert PlatformRecord.objects.filter(contract=contract).count() == 0


class TestEmpiricalCadenceDerivation:
    """Requirement: Empirical cadence derivation from payout history."""

    def test_two_payouts(self):
        records = [
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 1}),
            PlatformRecord(razorpay_created_at=_EPOCH + timedelta(days=30), payload={"amount": 1}),
        ]

        assert _compute_empirical_cadence_days(records) == pytest.approx(30.0)

    def test_three_payouts_evenly_spaced(self):
        records = [
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 1}),
            PlatformRecord(razorpay_created_at=_EPOCH + timedelta(days=30), payload={"amount": 1}),
            PlatformRecord(razorpay_created_at=_EPOCH + timedelta(days=60), payload={"amount": 1}),
        ]

        assert _compute_empirical_cadence_days(records) == pytest.approx(30.0)

    def test_outlier_skewed_set_median_resists_the_outlier(self):
        # Deltas: 30, 30, 1 - a mean would be dragged down to ~20.3; the
        # median (30) resists the single-day outlier delta.
        records = [
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 1}),
            PlatformRecord(razorpay_created_at=_EPOCH + timedelta(days=30), payload={"amount": 1}),
            PlatformRecord(razorpay_created_at=_EPOCH + timedelta(days=60), payload={"amount": 1}),
            PlatformRecord(razorpay_created_at=_EPOCH + timedelta(days=61), payload={"amount": 1}),
        ]

        assert _compute_empirical_cadence_days(records) == pytest.approx(30.0)


class TestEmpiricalAmountDerivation:
    """Requirement: Empirical amount derivation from payout history."""

    def test_two_payouts(self):
        records = [
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 500000}),
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 520000}),
        ]

        assert _compute_empirical_amount(records) == pytest.approx(5100.0)

    def test_three_payouts(self):
        records = [
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 500000}),
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 500000}),
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 500000}),
        ]

        assert _compute_empirical_amount(records) == pytest.approx(5000.0)

    def test_outlier_skewed_set_median_resists_the_outlier(self):
        records = [
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 500000}),
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 510000}),
            PlatformRecord(razorpay_created_at=_EPOCH, payload={"amount": 50000000}),
        ]

        assert _compute_empirical_amount(records) == pytest.approx(5100.0)


class TestCadenceMismatchDetection:
    """Requirement: Cadence mismatch detection against a configured tolerance."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2, AMOUNT_MISMATCH_TOLERANCE_PCT=0.05)
    @patch("core.llm_client.get_structured_completion")
    def test_within_tolerance_produces_no_flag(self, mock_completion):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        _cadence_term(numeric_value=1, unit="month", contract=contract)  # expects 30 days
        # 33-day empirical cadence is within 20% of 30 days.
        PlatformRecordFactory(contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 1})
        PlatformRecordFactory(
            contract=contract,
            razorpay_created_at=_EPOCH + timedelta(days=33),
            payload={"amount": 1},
        )

        flags = _run_payout_crosscheck(contract=contract)

        cadence_flags = [f for f in flags if f.mismatch_type == MismatchType.CADENCE_MISMATCH]
        assert cadence_flags == []
        mock_completion.assert_not_called()

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2, AMOUNT_MISMATCH_TOLERANCE_PCT=0.05)
    @patch("core.llm_client.get_structured_completion")
    def test_over_tolerance_creates_a_cadence_mismatch_flag(self, mock_completion):
        mock_completion.return_value = {
            "description": "Contract states monthly, but Payout history shows weekly.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"amount": 1',
        }
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        term = _cadence_term(numeric_value=1, unit="month", contract=contract)  # expects 30 days
        # 7-day empirical cadence deviates from 30 days by far more than 20%.
        PlatformRecordFactory(contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 1})
        PlatformRecordFactory(
            contract=contract, razorpay_created_at=_EPOCH + timedelta(days=7), payload={"amount": 1}
        )

        flags = _run_payout_crosscheck(contract=contract)

        cadence_flags = [f for f in flags if f.mismatch_type == MismatchType.CADENCE_MISMATCH]
        assert len(cadence_flags) == 1
        flag = cadence_flags[0]
        assert flag.extracted_term_id == term.id
        assert flag.platform_record is not None
        assert MismatchFlag.objects.filter(id=flag.id).exists()


class TestAmountMismatchDetection:
    """Requirement: Amount mismatch detection against a configured tolerance."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2, AMOUNT_MISMATCH_TOLERANCE_PCT=0.05)
    @patch("core.llm_client.get_structured_completion")
    def test_within_tolerance_produces_no_flag(self, mock_completion):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        _amount_term(numeric_value=5000, contract=contract)  # rupees
        # Empirical amount ~5100 rupees is within 5% of 5000.
        PlatformRecordFactory(
            contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 500000}
        )
        PlatformRecordFactory(
            contract=contract,
            razorpay_created_at=_EPOCH + timedelta(days=30),
            payload={"amount": 520000},
        )

        flags = _run_payout_crosscheck(contract=contract)

        amount_flags = [f for f in flags if f.mismatch_type == MismatchType.AMOUNT_MISMATCH]
        assert amount_flags == []
        mock_completion.assert_not_called()

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2, AMOUNT_MISMATCH_TOLERANCE_PCT=0.05)
    @patch("core.llm_client.get_structured_completion")
    def test_over_tolerance_creates_an_amount_mismatch_flag(self, mock_completion):
        mock_completion.return_value = {
            "description": "Contract states 5000 but observed Payout history shows 8000.",
            "expected_quote": "an amount of 5000",
            "actual_quote": '"amount": 800000',
        }
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        term = _amount_term(numeric_value=5000, contract=contract)
        PlatformRecordFactory(
            contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 800000}
        )
        PlatformRecordFactory(
            contract=contract,
            razorpay_created_at=_EPOCH + timedelta(days=30),
            payload={"amount": 800000},
        )

        flags = _run_payout_crosscheck(contract=contract)

        amount_flags = [f for f in flags if f.mismatch_type == MismatchType.AMOUNT_MISMATCH]
        assert len(amount_flags) == 1
        assert amount_flags[0].extracted_term_id == term.id
        assert amount_flags[0].platform_record is not None


class TestMissingPlatformEvidence:
    """Requirement: Missing platform evidence when insufficient payout history exists."""

    @patch("core.llm_client.get_structured_completion")
    def test_zero_payouts_creates_missing_platform_evidence_flag(self, mock_completion):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        term = _cadence_term(numeric_value=1, unit="month", contract=contract)

        flags = _run_payout_crosscheck(contract=contract)

        assert len(flags) == 1
        assert flags[0].mismatch_type == MismatchType.MISSING_PLATFORM_EVIDENCE
        assert flags[0].extracted_term_id == term.id
        assert flags[0].platform_record is None
        mock_completion.assert_not_called()

    @patch("core.llm_client.get_structured_completion")
    def test_one_payout_creates_missing_platform_evidence_flag(self, mock_completion):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        term = _cadence_term(numeric_value=1, unit="month", contract=contract)
        PlatformRecordFactory(contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 1})

        flags = _run_payout_crosscheck(contract=contract)

        assert len(flags) == 1
        assert flags[0].mismatch_type == MismatchType.MISSING_PLATFORM_EVIDENCE
        assert flags[0].extracted_term_id == term.id
        assert flags[0].platform_record is None
        mock_completion.assert_not_called()


class TestNoScheduleConfigurationClaim:
    """Requirement: No claim of a payout schedule configuration."""

    _FORBIDDEN_PHRASES = ("schedule config", "payout schedule", "schedule configuration")

    @patch("core.llm_client.get_structured_completion")
    def test_cadence_mismatch_description_never_claims_a_schedule_config(self, mock_completion):
        mock_completion.return_value = {
            "description": "Contract states monthly, but observed Payout history shows weekly.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"amount": 1',
        }
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        _cadence_term(numeric_value=1, unit="month", contract=contract)
        PlatformRecordFactory(contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 1})
        PlatformRecordFactory(
            contract=contract, razorpay_created_at=_EPOCH + timedelta(days=7), payload={"amount": 1}
        )

        with override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2):
            flags = _run_payout_crosscheck(contract=contract)

        for flag in flags:
            for phrase in self._FORBIDDEN_PHRASES:
                assert phrase not in flag.description.lower()

    def test_missing_evidence_description_never_claims_a_schedule_config(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        _cadence_term(numeric_value=1, unit="month", contract=contract)

        flags = _run_payout_crosscheck(contract=contract)

        for flag in flags:
            for phrase in self._FORBIDDEN_PHRASES:
                assert phrase not in flag.description.lower()

    def test_deterministic_template_fallback_never_claims_a_schedule_config(self):
        from razorpay_integration.services import _deterministic_template_description

        description = _deterministic_template_description(
            mismatch_type=MismatchType.CADENCE_MISMATCH.value,
            expected_value={"numeric_value": 1, "unit": "month"},
            actual_value={"empirical_cadence_days": 7.0},
        )

        for phrase in self._FORBIDDEN_PHRASES:
            assert phrase not in description.lower()


class _FakeConnector:
    """A stand-in for RazorpayConnector returning canned responses, no network calls."""

    def __init__(self, *, payouts_response=None, subscription_response=None, token_response=None):
        self._payouts_response = payouts_response or {"items": []}
        self._subscription_response = subscription_response or {}
        self._token_response = token_response or {"items": []}

    def fetch_payouts(self, *, fund_account_id):
        return self._payouts_response

    def fetch_subscription(self, *, subscription_id):
        return self._subscription_response

    def fetch_token(self, *, customer_id):
        return self._token_response
