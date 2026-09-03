"""Standing guardrail tests (task 9).

9.1: the production-path connector issues only GET requests against any
live-data endpoint, verified against a mocked transport that fails on any
non-GET call.
9.2: every MismatchFlag produced by a pipeline run has a non-null
extracted_term_id and a fully resolvable reasoning chain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import razorpay
from django.test import override_settings

from contracts.models import RazorpayReferenceType
from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.models import TermType
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.client import RazorpayConnector
from razorpay_integration.services import _run_payout_crosscheck
from razorpay_integration.tests.factories import PlatformRecordFactory

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class TestConnectorOnlyEverDispatchesGetRequests:
    """Requirement: the production cross-check path issues GET calls only."""

    def test_connector_only_ever_dispatches_get_requests(self, monkeypatch):
        dispatched_methods: list[str] = []

        def fake_request(self, method, path, **options):
            dispatched_methods.append(method)
            assert method == "get", f"non-GET call dispatched: {method.upper()} {path}"
            return {"items": []}

        monkeypatch.setattr(razorpay.Client, "request", fake_request)

        connector = RazorpayConnector(key_id="rzp_test_id", key_secret="rzp_test_secret")
        connector.fetch_payouts(fund_account_id="fa_00000000000001")
        connector.fetch_subscription(subscription_id="sub_1")
        connector.fetch_token(customer_id="cust_1")

        assert dispatched_methods, "expected at least one dispatched call"
        assert all(method == "get" for method in dispatched_methods)


@pytest.mark.django_db
class TestEveryMismatchFlagHasAResolvableEvidenceChain:
    """Requirement: every MismatchFlag has a non-null extracted_term and resolvable chain."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2)
    @patch("core.llm_client.get_structured_completion")
    def test_sample_pipeline_run_flags_all_have_a_resolvable_chain(self, mock_completion):
        mock_completion.return_value = {
            "description": "Contract states monthly, but Payout history shows weekly.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"amount": 1',
        }
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
        )
        PlatformRecordFactory(contract=contract, razorpay_created_at=_EPOCH, payload={"amount": 1})
        PlatformRecordFactory(
            contract=contract, razorpay_created_at=_EPOCH + timedelta(days=7), payload={"amount": 1}
        )
        # A second, unrelated contract with its own missing-evidence flag,
        # to prove the check below is per-flag and not just "any flag
        # exists somewhere".
        other_contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        other_clause = ClauseFactory(contract=other_contract)
        ExtractedTermFactory(
            clause=other_clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_structured={"numeric_value": 1, "unit": "week"},
        )

        flags = _run_payout_crosscheck(contract=contract) + _run_payout_crosscheck(
            contract=other_contract
        )
        assert len(flags) == 2

        for flag in flags:
            assert flag.extracted_term_id is not None
            # clause -> extracted_term
            term = flag.extracted_term
            assert term.clause_id is not None
            # extracted_term -> platform_record or explicit missing-evidence
            if flag.platform_record_id is None:
                assert flag.mismatch_type in (
                    "missing_platform_evidence",
                    "trigger_condition_unverifiable",
                )
            else:
                assert flag.platform_record.contract_id == term.clause.contract_id
            # -> description
            assert flag.description
