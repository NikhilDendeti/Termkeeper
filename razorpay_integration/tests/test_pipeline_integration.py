"""Tests for the stage-4 orchestrator and its wiring into pipeline.services.run_pipeline.

See design.md (add-razorpay-crosscheck) - "Extending run_pipeline without a
circular import." `risk_scoring.services.score_clause` (pipeline stage 5,
added in add-risk-scoring-report) is mocked in the full-run tests below
purely to keep this module's `mock_completion.call_count` assertions scoped
to stages 1-4 - stage 5's own behavior is covered by risk_scoring/tests/.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings

from contracts.models import Clause, RazorpayReferenceType
from contracts.tests.factories import ContractFactory
from pipeline.models import AuditLogEntry, ExtractedTerm
from razorpay_integration.models import MismatchFlag, MismatchType
from razorpay_integration.services import detect_mismatches

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class TestDetectMismatchesOrchestrator:
    """Requirement (task 7.1): branch on razorpay_reference_type, run the matching cross-check."""

    @pytest.mark.django_db
    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2)
    @patch("core.llm_client.get_structured_completion")
    def test_payout_referenced_contract_runs_the_payout_crosscheck(self, mock_completion):
        mock_completion.return_value = {
            "description": "Contract states monthly, but Payout history shows weekly.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"amount": 1',
        }
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = Clause.objects.create(contract=contract, sequence_index=0, clause_text="x")
        ExtractedTerm.objects.create(
            clause=clause,
            term_type="payout_frequency",
            value_raw="paid every 1 month",
            value_structured={"numeric_value": 1, "unit": "month"},
            extraction_confidence=0.9,
        )
        fake_connector = _payout_connector(
            [
                {"id": "pout_1", "amount": 1, "created_at": int(_EPOCH.timestamp())},
                {
                    "id": "pout_2",
                    "amount": 1,
                    "created_at": int((_EPOCH + timedelta(days=7)).timestamp()),
                },
            ]
        )

        with patch("razorpay_integration.services.RazorpayConnector", return_value=fake_connector):
            flags = detect_mismatches(contract=contract)

        assert len(flags) == 1
        assert flags[0].mismatch_type == MismatchType.CADENCE_MISMATCH

    @pytest.mark.django_db
    def test_subscription_referenced_contract_runs_the_subscription_crosscheck(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        clause = Clause.objects.create(contract=contract, sequence_index=0, clause_text="x")
        ExtractedTerm.objects.create(
            clause=clause,
            term_type="milestone_trigger",
            value_raw="upon completion",
            value_structured={"numeric_value": None, "unit": None},
            extraction_confidence=0.9,
        )
        fake_connector = _subscription_connector(
            {
                "id": "sub_1",
                "customer_id": "cust_1",
                "period": "monthly",
                "interval": 1,
                "item": {"amount": 1},
                "created_at": int(_EPOCH.timestamp()),
            }
        )

        with patch("razorpay_integration.services.RazorpayConnector", return_value=fake_connector):
            flags = detect_mismatches(contract=contract)

        assert len(flags) == 1
        assert flags[0].mismatch_type == MismatchType.TRIGGER_CONDITION_UNVERIFIABLE


def _payout_connector(items):
    class _Connector:
        def fetch_payouts(self, *, fund_account_id):
            return {"items": items}

        def fetch_subscription(self, *, subscription_id):  # pragma: no cover
            raise AssertionError("subscription path must not run for a payout contract")

        def fetch_token(self, *, customer_id):  # pragma: no cover
            raise AssertionError("subscription path must not run for a payout contract")

    return _Connector()


def _subscription_connector(subscription_payload, token_items=None):
    class _Connector:
        def fetch_subscription(self, *, subscription_id):
            return subscription_payload

        def fetch_token(self, *, customer_id):
            return {"items": token_items or []}

        def fetch_payouts(self, *, fund_account_id):  # pragma: no cover
            raise AssertionError("payout path must not run for a subscription contract")

    return _Connector()


class TestPipelineServicesImportIsolation:
    """`pipeline.services` must not import `razorpay_integration` at module scope.

    The dependency on `razorpay_integration.services.detect_mismatches` is
    resolved via a function-local import inside `run_pipeline` itself - see
    design.md's circular-import decision. Verified in a fresh subprocess so
    nothing else in the test session could have already pre-imported
    `razorpay_integration`.
    """

    def test_pipeline_services_imports_without_razorpay_integration_preloaded(self):
        # `razorpay_integration` (the package) and `razorpay_integration.models`
        # are unavoidably imported by Django's app registry at `django.setup()`
        # time, since the app is registered in INSTALLED_APPS - that is not
        # what this test guards against. What must NOT happen is
        # `razorpay_integration.services` (which is what run_pipeline's
        # function-local import pulls in) being imported merely as a side
        # effect of importing `pipeline.services` at module scope.
        script = (
            "import django, os\n"
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')\n"
            "django.setup()\n"
            "import sys\n"
            "assert 'razorpay_integration.services' not in sys.modules\n"
            "import pipeline.services\n"
            "assert 'razorpay_integration.services' not in sys.modules, ("
            "'pipeline.services must not import razorpay_integration.services at module scope')\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout


@pytest.mark.django_db
class TestRunPipelineEndToEnd:
    """Task 7.2: run_pipeline(contract=contract) produces MismatchFlag rows."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2, ENABLE_STAGE_4=True)
    @patch("risk_scoring.services.score_clause")
    @patch("core.llm_client.get_structured_completion")
    def test_full_run_produces_mismatch_flags_for_a_payout_contract(
        self, mock_completion, mock_score_clause
    ):
        from pipeline.services import run_pipeline

        payment_clause_text = (
            "1. Payment Schedule. Vendor shall be paid every 1 month, at an "
            "amount of 5000 per payout."
        )
        contract = ContractFactory(
            raw_text=payment_clause_text, razorpay_reference_type=RazorpayReferenceType.PAYOUT
        )

        segmentation_response = {"clauses": [{"text": payment_clause_text}]}
        classification_response = {
            "primary_label": "payment_schedule",
            "primary_confidence": 0.9,
            "secondary_label": "termination",
            "secondary_confidence": 0.1,
            "rationale": "States a monthly payout schedule and amount.",
        }
        extraction_response = {
            "terms": [
                {
                    "term_type": "payout_frequency",
                    "value_raw": "paid every 1 month",
                    "numeric_value": 1,
                    "unit": "month",
                    "is_formula_based": False,
                    "confidence": 0.9,
                }
            ]
        }
        description_response = {
            "description": "Contract states monthly, but Payout history shows weekly.",
            "expected_quote": "paid every 1 month",
            "actual_quote": '"amount": 1',
        }
        mock_completion.side_effect = [
            segmentation_response,
            classification_response,
            extraction_response,
            description_response,
        ]

        fake_connector = _payout_connector(
            [
                {"id": "pout_1", "amount": 1, "created_at": int(_EPOCH.timestamp())},
                {
                    "id": "pout_2",
                    "amount": 1,
                    "created_at": int((_EPOCH + timedelta(days=7)).timestamp()),
                },
            ]
        )

        with patch("razorpay_integration.services.RazorpayConnector", return_value=fake_connector):
            run_pipeline(contract=contract, from_stage=1)

        assert mock_completion.call_count == 4
        flags = list(MismatchFlag.objects.filter(extracted_term__clause__contract=contract))
        assert len(flags) == 1
        assert flags[0].mismatch_type == MismatchType.CADENCE_MISMATCH
        assert AuditLogEntry.objects.filter(contract=contract, stage=4).count() == 1

    @override_settings(ENABLE_STAGE_4=False)
    @patch("risk_scoring.services.score_clause")
    @patch("core.llm_client.get_structured_completion")
    def test_stage_4_is_skipped_when_disabled_via_settings(
        self, mock_completion, mock_score_clause
    ):
        from pipeline.services import run_pipeline

        payment_clause_text = "1. Payment Schedule. Vendor shall be paid net 30 days."
        contract = ContractFactory(
            raw_text=payment_clause_text, razorpay_reference_type=RazorpayReferenceType.PAYOUT
        )
        mock_completion.side_effect = [
            {"clauses": [{"text": payment_clause_text}]},
            {
                "primary_label": "payment_schedule",
                "primary_confidence": 0.9,
                "secondary_label": "termination",
                "secondary_confidence": 0.1,
                "rationale": "States a 30-day payment term.",
            },
            {
                "terms": [
                    {
                        "term_type": "payout_frequency",
                        "value_raw": "net 30 days",
                        "numeric_value": 30,
                        "unit": "days",
                        "is_formula_based": False,
                        "confidence": 0.9,
                    }
                ]
            },
        ]

        with patch("razorpay_integration.services.RazorpayConnector") as mock_connector_cls:
            run_pipeline(contract=contract, from_stage=1)

        mock_connector_cls.assert_not_called()
        assert mock_completion.call_count == 3
        assert not MismatchFlag.objects.filter(extracted_term__clause__contract=contract).exists()
