"""Tests for the live overdue-payment-detection selector.

Spec: specs/razorpay-integration/overdue-payment-detection/spec.md.
`list_overdue_statuses` is a pure read over already-persisted rows - no
RazorpayConnector call, no core.llm_client call, no ENABLE_STAGE_4 gate
needed anywhere in this file. Every fixture timestamp is built relative to
`timezone.now()` at test-run time (never a fixed wall-clock date), per
design.md's "tests avoid the flakiness by constructing fixture timestamps
relative to timezone.now()" note.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from contracts.models import RazorpayReferenceType
from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.models import TermType
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.models import PlatformRecordType
from razorpay_integration import services as services_module
from razorpay_integration.selectors import OverdueStatus, list_overdue_statuses
from razorpay_integration.tests.factories import PlatformRecordFactory

pytestmark = pytest.mark.django_db


def _cadence_term(*, clause, numeric_value: float = 30, unit: str = "days"):
    return ExtractedTermFactory(
        clause=clause,
        term_type=TermType.PAYOUT_FREQUENCY,
        value_raw=f"paid every {numeric_value} {unit}",
        value_structured={"numeric_value": numeric_value, "unit": unit},
    )


def _payout_record(*, contract, days_ago: float):
    return PlatformRecordFactory(
        contract=contract,
        record_type=PlatformRecordType.PAYOUT,
        razorpay_created_at=timezone.now() - timedelta(days=days_ago),
    )


class TestNotOverdue:
    """Spec scenario: Well within the expected interval is not overdue."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2)
    def test_last_payout_well_within_the_cadence_interval(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        term = _cadence_term(clause=clause, numeric_value=30, unit="days")
        _payout_record(contract=contract, days_ago=5)

        statuses = list_overdue_statuses(contract=contract)

        assert len(statuses) == 1
        assert statuses[0].term_id == term.id
        assert statuses[0].is_overdue is False
        assert statuses[0].expected_interval_days == 30.0
        assert statuses[0].days_since_last_payout == 5


class TestOverdue:
    """Spec scenario: Past the interval and tolerance is overdue."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2)
    def test_last_payout_past_interval_plus_tolerance(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        term = _cadence_term(clause=clause, numeric_value=30, unit="days")
        # boundary = 30 * 1.2 = 36 days; 40 is comfortably past it.
        _payout_record(contract=contract, days_ago=40)

        statuses = list_overdue_statuses(contract=contract)

        assert len(statuses) == 1
        assert statuses[0].term_id == term.id
        assert statuses[0].is_overdue is True
        assert statuses[0].days_since_last_payout == 40


class TestToleranceBoundary:
    """Spec scenario: Exactly at the tolerance boundary is not overdue."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2)
    def test_exactly_at_the_boundary_is_not_overdue(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        _cadence_term(clause=clause, numeric_value=30, unit="days")
        # boundary = 30 * (1 + 0.2) = 36.0 days, exactly.
        _payout_record(contract=contract, days_ago=36)

        statuses = list_overdue_statuses(contract=contract)

        assert len(statuses) == 1
        assert statuses[0].is_overdue is False

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2)
    def test_one_day_past_the_boundary_is_overdue(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        _cadence_term(clause=clause, numeric_value=30, unit="days")
        _payout_record(contract=contract, days_ago=37)

        statuses = list_overdue_statuses(contract=contract)

        assert len(statuses) == 1
        assert statuses[0].is_overdue is True


class TestZeroPlatformRecords:
    """Spec scenario: Contract with no Payout records yields an empty result."""

    def test_zero_payout_records_yields_empty_not_a_false_overdue(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        _cadence_term(clause=clause, numeric_value=30, unit="days")

        assert list_overdue_statuses(contract=contract) == []


class TestAmountTypeTermExcluded:
    """Spec scenario: Amount-type payout_frequency term is excluded."""

    def test_amount_type_term_never_produces_a_status(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="a flat fee of 500 INR per payout",
            value_structured={"numeric_value": 500, "unit": "INR"},
        )
        # Even with Payout history that would otherwise be well overdue -
        # an amount term has no interval to be late against.
        _payout_record(contract=contract, days_ago=400)

        assert list_overdue_statuses(contract=contract) == []


class TestSubscriptionReferencedContractExcluded:
    """Spec scenario: Subscription-referenced contract yields no overdue statuses."""

    def test_subscription_contract_yields_empty_list(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        clause = ClauseFactory(contract=contract)
        _cadence_term(clause=clause, numeric_value=30, unit="days")

        assert list_overdue_statuses(contract=contract) == []


class TestMultipleQualifyingTerms:
    """Spec scenario: Multiple qualifying terms each produce their own status."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2)
    def test_two_terms_on_different_clauses_each_get_their_own_status(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        overdue_clause = ClauseFactory(contract=contract, sequence_index=0)
        not_overdue_clause = ClauseFactory(contract=contract, sequence_index=1)
        overdue_term = _cadence_term(clause=overdue_clause, numeric_value=30, unit="days")
        not_overdue_term = _cadence_term(clause=not_overdue_clause, numeric_value=60, unit="days")
        # Same observed Payout history for both: 40 days since the last one.
        # 40 > 30*1.2=36 -> overdue; 40 <= 60*1.2=72 -> not overdue.
        _payout_record(contract=contract, days_ago=40)

        statuses = list_overdue_statuses(contract=contract)

        by_term_id = {status.term_id: status for status in statuses}
        assert set(by_term_id) == {overdue_term.id, not_overdue_term.id}
        assert by_term_id[overdue_term.id].is_overdue is True
        assert by_term_id[not_overdue_term.id].is_overdue is False

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2)
    def test_two_terms_on_the_same_clause_each_get_their_own_status(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        term_a = _cadence_term(clause=clause, numeric_value=30, unit="days")
        term_b = _cadence_term(clause=clause, numeric_value=7, unit="days")
        _payout_record(contract=contract, days_ago=40)

        statuses = list_overdue_statuses(contract=contract)

        by_term_id = {status.term_id: status for status in statuses}
        assert set(by_term_id) == {term_a.id, term_b.id}
        # 40 > 30*1.2=36 -> overdue; 40 > 7*1.2=8.4 -> also overdue, but each
        # keeps its own expected_interval_days independently.
        assert by_term_id[term_a.id].expected_interval_days == 30.0
        assert by_term_id[term_b.id].expected_interval_days == 7.0


class TestNonCadenceNonPayoutFrequencyTermsIgnored:
    def test_non_payout_frequency_term_type_never_produces_a_status(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.NOTICE_PERIOD,
            value_raw="30 days notice",
            value_structured={"numeric_value": 30, "unit": "days"},
        )
        _payout_record(contract=contract, days_ago=400)

        assert list_overdue_statuses(contract=contract) == []


class TestLatestPayoutDateUsesTheMostRecentRecord:
    def test_uses_the_max_razorpay_created_at_across_payout_records(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        _cadence_term(clause=clause, numeric_value=30, unit="days")
        # An older record and a more recent one - the more recent one must
        # be the one measured against, not the older one (which alone would
        # read as overdue).
        _payout_record(contract=contract, days_ago=100)
        recent = _payout_record(contract=contract, days_ago=5)

        statuses = list_overdue_statuses(contract=contract)

        assert len(statuses) == 1
        assert statuses[0].is_overdue is False
        assert statuses[0].latest_payout_date == recent.razorpay_created_at


class TestOverdueDetectionNeverRunsDuringStage4:
    """Spec requirement: Overdue detection never runs during stage-4 mismatch
    detection - `detect_mismatches` and everything it calls must never
    reference `list_overdue_statuses`/`OverdueStatus`, mirroring
    test_fixtures_isolation.py's phrase-absence style of enforcement."""

    def test_services_module_source_never_references_overdue_detection(self):
        source = inspect.getsource(services_module)
        assert "list_overdue_statuses" not in source
        assert "OverdueStatus" not in source

    def test_overdue_status_is_a_frozen_dataclass(self):
        status = OverdueStatus(
            term_id=uuid.uuid4(),
            is_overdue=True,
            days_since_last_payout=40,
            expected_interval_days=30.0,
            latest_payout_date=timezone.now(),
        )
        with pytest.raises(Exception):
            status.is_overdue = False
