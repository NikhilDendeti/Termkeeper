"""Tests for the secondary (Subscription/UPI Autopay) cross-check path.

Spec: specs/razorpay-integration/subscription-crosscheck/spec.md.
Every RazorpayConnector call and every core.llm_client call is mocked -
no real network call is made.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from contracts.models import RazorpayReferenceType
from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.models import TermType
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.models import MismatchFlag, MismatchType, PlatformRecordType
from razorpay_integration.services import (
    _run_subscription_crosscheck,
    detect_mismatches,
    fetch_subscription_config,
)
from razorpay_integration.tests.factories import PlatformRecordFactory

pytestmark = pytest.mark.django_db

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_EPOCH_TS = int(_EPOCH.timestamp())


def _subscription_payload(*, subscription_id="sub_1", customer_id="cust_1", amount_paise=500000):
    return {
        "id": subscription_id,
        "entity": "subscription",
        "customer_id": customer_id,
        "period": "monthly",
        "interval": 1,
        "item": {"amount": amount_paise},
        "total_count": 12,
        "created_at": _EPOCH_TS,
    }


def _token_item(
    *, token_id="token_1", status="active", created_at=_EPOCH_TS, max_amount_paise=500000
):
    return {
        "id": token_id,
        "status": status,
        "max_amount": max_amount_paise,
        "expire_at": created_at + 86400 * 365,
        "created_at": created_at,
    }


class _FakeConnector:
    def __init__(self, *, subscription_response=None, token_response=None):
        self._subscription_response = subscription_response or {}
        self._token_response = token_response or {"items": []}
        self.fetch_subscription_calls: list[str] = []
        self.fetch_token_calls: list[str] = []

    def fetch_subscription(self, *, subscription_id):
        self.fetch_subscription_calls.append(subscription_id)
        return self._subscription_response

    def fetch_token(self, *, customer_id):
        self.fetch_token_calls.append(customer_id)
        return self._token_response

    def fetch_payouts(self, *, fund_account_id):
        return {"items": []}


class TestFetchSubscriptionConfig:
    """Requirement: Subscription and token fields fetched for diffing."""

    def test_subscription_and_token_persisted_with_correct_payload(self):
        contract = ContractFactory(
            razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION,
            razorpay_reference_id="sub_1",
        )
        subscription_payload = _subscription_payload()
        token_payload = _token_item()
        fake_connector = _FakeConnector(
            subscription_response=subscription_payload,
            token_response={"items": [token_payload]},
        )

        with patch("razorpay_integration.services.RazorpayConnector", return_value=fake_connector):
            records = fetch_subscription_config(contract=contract)

        assert len(records) == 2
        subscription_records = [
            r for r in records if r.record_type == PlatformRecordType.SUBSCRIPTION
        ]
        token_records = [r for r in records if r.record_type == PlatformRecordType.TOKEN]
        assert len(subscription_records) == 1
        assert len(token_records) == 1
        assert subscription_records[0].payload == subscription_payload
        assert token_records[0].payload == token_payload
        assert fake_connector.fetch_subscription_calls == ["sub_1"]
        assert fake_connector.fetch_token_calls == ["cust_1"]

    def test_selects_the_freshest_non_cancelled_token(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        older_active = _token_item(token_id="token_old", created_at=_EPOCH_TS)
        newer_cancelled = _token_item(
            token_id="token_cancelled", created_at=_EPOCH_TS + 1000, status="cancelled"
        )
        newest_active = _token_item(token_id="token_new", created_at=_EPOCH_TS + 2000)
        fake_connector = _FakeConnector(
            subscription_response=_subscription_payload(),
            token_response={"items": [older_active, newer_cancelled, newest_active]},
        )

        with patch("razorpay_integration.services.RazorpayConnector", return_value=fake_connector):
            records = fetch_subscription_config(contract=contract)

        token_records = [r for r in records if r.record_type == PlatformRecordType.TOKEN]
        assert len(token_records) == 1
        assert token_records[0].razorpay_id == "token_new"


class TestSecondaryPathRestrictedToSubscriptionContracts:
    """Requirement: Secondary path restricted to subscription-referenced contracts."""

    def test_payout_referenced_contract_skips_subscription_crosscheck_entirely(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        fake_connector = _FakeConnector(subscription_response=_subscription_payload())

        with patch("razorpay_integration.services.RazorpayConnector", return_value=fake_connector):
            records = fetch_subscription_config(contract=contract)

        assert records == []
        assert fake_connector.fetch_subscription_calls == []
        assert fake_connector.fetch_token_calls == []

    @patch("core.llm_client.get_structured_completion")
    def test_detect_mismatches_issues_no_subscription_or_token_calls_for_payout_contract(
        self, mock_completion
    ):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        fake_connector = _FakeConnector(subscription_response=_subscription_payload())

        with patch("razorpay_integration.services.RazorpayConnector", return_value=fake_connector):
            detect_mismatches(contract=contract)

        assert fake_connector.fetch_subscription_calls == []
        assert fake_connector.fetch_token_calls == []
        assert not MismatchFlag.objects.filter(
            mismatch_type__in=[
                MismatchType.TRIGGER_CONDITION_UNVERIFIABLE,
            ]
        ).exists()


class TestExactFieldDiffNoTolerance:
    """Requirement: Exact field diff with no tolerance band."""

    @patch("core.llm_client.get_structured_completion")
    def test_any_nonzero_item_amount_difference_creates_amount_mismatch(self, mock_completion):
        mock_completion.return_value = {
            "description": "Contract states 5000 but Subscription item.amount is 5001.",
            "expected_quote": "an amount of 5000",
            "actual_quote": '"amount": 500100',
        }
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        clause = ClauseFactory(contract=contract)
        term = ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="an amount of 5000",
            value_structured={"numeric_value": 5000, "unit": "INR"},
        )
        subscription_record = PlatformRecordFactory(
            contract=contract,
            record_type=PlatformRecordType.SUBSCRIPTION,
            razorpay_created_at=_EPOCH,
            # 500100 paise = 5001.00 rupees - one rupee off from the
            # contract-stated 5000, well under any realistic percentage
            # tolerance, but still an exact-diff mismatch.
            payload=_subscription_payload(amount_paise=500100),
        )

        flags = _run_subscription_crosscheck(contract=contract)

        amount_flags = [f for f in flags if f.mismatch_type == MismatchType.AMOUNT_MISMATCH]
        assert len(amount_flags) == 1
        assert amount_flags[0].extracted_term_id == term.id
        assert amount_flags[0].platform_record_id == subscription_record.id

    @patch("core.llm_client.get_structured_completion")
    def test_matching_fields_produce_no_flag(self, mock_completion):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        clause = ClauseFactory(contract=contract)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="an amount of 5000",
            value_structured={"numeric_value": 5000, "unit": "INR"},
        )
        PlatformRecordFactory(
            contract=contract,
            record_type=PlatformRecordType.SUBSCRIPTION,
            razorpay_created_at=_EPOCH,
            payload=_subscription_payload(amount_paise=500000),
        )

        flags = _run_subscription_crosscheck(contract=contract)

        assert flags == []
        mock_completion.assert_not_called()

    @patch("core.llm_client.get_structured_completion")
    def test_matching_cadence_fields_produce_no_flag(self, mock_completion):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        clause = ClauseFactory(contract=contract)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
        )
        PlatformRecordFactory(
            contract=contract,
            record_type=PlatformRecordType.SUBSCRIPTION,
            razorpay_created_at=_EPOCH,
            payload=_subscription_payload(),
        )

        flags = _run_subscription_crosscheck(contract=contract)

        assert flags == []
        mock_completion.assert_not_called()

    @patch("core.llm_client.get_structured_completion")
    def test_mismatched_cadence_fields_create_cadence_mismatch(self, mock_completion):
        mock_completion.return_value = {
            "description": "Contract states monthly, Subscription period is weekly.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"period": "weekly"',
        }
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        clause = ClauseFactory(contract=contract)
        term = ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
        )
        payload = _subscription_payload()
        payload["period"] = "weekly"
        payload["interval"] = 1
        PlatformRecordFactory(
            contract=contract,
            record_type=PlatformRecordType.SUBSCRIPTION,
            razorpay_created_at=_EPOCH,
            payload=payload,
        )

        flags = _run_subscription_crosscheck(contract=contract)

        cadence_flags = [f for f in flags if f.mismatch_type == MismatchType.CADENCE_MISMATCH]
        assert len(cadence_flags) == 1
        assert cadence_flags[0].extracted_term_id == term.id


class TestTriggerConditionUnverifiable:
    """Requirement: Trigger condition unverifiable for non-diffable terms."""

    def test_milestone_trigger_term_produces_trigger_condition_unverifiable(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        clause = ClauseFactory(contract=contract)
        term = ExtractedTermFactory(
            clause=clause,
            term_type=TermType.MILESTONE_TRIGGER,
            value_raw="upon completion of the design milestone",
            value_structured={"numeric_value": None, "unit": None},
        )

        flags = _run_subscription_crosscheck(contract=contract)

        assert len(flags) == 1
        flag = flags[0]
        assert flag.mismatch_type == MismatchType.TRIGGER_CONDITION_UNVERIFIABLE
        assert flag.extracted_term_id == term.id
        assert flag.platform_record is None
