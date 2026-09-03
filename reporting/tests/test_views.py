"""Tests for reporting.views (tasks 7.2-7.5, and tasks 4.1-4.3 additions)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from django.urls import reverse

from contracts.models import RazorpayReferenceType
from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.models import TermType
from pipeline.tests.factories import AuditLogEntryFactory, ExtractedTermFactory
from razorpay_integration.models import PlatformRecordType
from razorpay_integration.tests.factories import MismatchFlagFactory, PlatformRecordFactory
from reporting.selectors import GuardrailScanResult, GuardrailViolation
from risk_scoring.models import SeverityChoices
from risk_scoring.tests.factories import RiskAssessmentFactory

pytestmark = pytest.mark.django_db


class TestContractReportAPIView:
    """Task 7.2 / spec: Retrieve-only report endpoint."""

    def test_get_returns_200_with_the_expected_payload_shape(self, client):
        contract = ContractFactory()
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract), severity=SeverityChoices.HIGH
        )

        url = reverse("contract-report", kwargs={"contract_id": contract.id})
        response = client.get(url)

        assert response.status_code == 200
        body = response.json()
        assert body["contract_id"] == str(contract.id)
        assert body["overall_risk_score"] == 0.75
        assert "flagged_clauses" in body
        assert "platform_mismatches" in body
        assert "needs_human_review_clauses" in body
        assert body["flagged_clauses"][0]["severity"] == "high"

    def test_severity_breakdown_by_clause_type_appears_in_the_live_response(self, client):
        """Task 1.4 / spec: reporting/clause-type-breakdown."""
        contract = ContractFactory()
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract, clause_type="termination"),
            severity=SeverityChoices.HIGH,
            asymmetry_score=0.6,
        )

        url = reverse("contract-report", kwargs={"contract_id": contract.id})
        response = client.get(url)

        assert response.status_code == 200
        body = response.json()
        assert body["severity_breakdown_by_clause_type"] == {
            "termination": {"count": 1, "mean_asymmetry_score": 0.6},
        }

    def test_unknown_contract_id_returns_404_with_no_report_body(self, client):
        """Task 7.3 / spec: Unknown contract is rejected."""
        url = reverse("contract-report", kwargs={"contract_id": uuid.uuid4()})

        response = client.get(url)

        assert response.status_code == 404
        assert "overall_risk_score" not in response.content.decode()


class TestContractAuditTrailAPIView:
    """Task 7.4 / spec: Audit trail exposed through the same surface."""

    def test_entries_from_every_stage_appear_ordered_oldest_first(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(contract=contract)
        for stage in [1, 2, 3, 4, 5]:
            entry_clause = clause if stage != 1 else None
            AuditLogEntryFactory(contract=contract, clause=entry_clause, stage=stage)

        url = reverse("contract-audit-trail", kwargs={"contract_id": contract.id})
        response = client.get(url)

        assert response.status_code == 200
        body = response.json()
        assert [entry["stage"] for entry in body] == [1, 2, 3, 4, 5]

    def test_unknown_contract_id_returns_404(self, client):
        url = reverse("contract-audit-trail", kwargs={"contract_id": uuid.uuid4()})

        response = client.get(url)

        assert response.status_code == 404


class TestUrlsResolve:
    """Task 7.5: both routes resolve via reverse()."""

    def test_contract_report_url_resolves(self):
        contract_id = uuid.uuid4()
        url = reverse("contract-report", kwargs={"contract_id": contract_id})
        assert str(contract_id) in url
        assert url.endswith("/report/")

    def test_contract_audit_trail_url_resolves(self):
        contract_id = uuid.uuid4()
        url = reverse("contract-audit-trail", kwargs={"contract_id": contract_id})
        assert str(contract_id) in url
        assert url.endswith("/audit-trail/")

    def test_contract_list_url_resolves(self):
        url = reverse("contract-list")
        assert url.endswith("/contracts/")

    def test_contract_reasoning_chain_url_resolves(self):
        contract_id = uuid.uuid4()
        url = reverse("contract-reasoning-chain", kwargs={"contract_id": contract_id})
        assert str(contract_id) in url
        assert url.endswith("/reasoning-chain/")

    def test_guardrail_verification_url_resolves(self):
        url = reverse("guardrail-verification")
        assert url.endswith("/guardrail-verification/")


class TestContractListAPIView:
    """Task 4.1 / spec: api/contract-listing."""

    def test_contracts_returned_newest_first(self, client):
        first = ContractFactory()
        second = ContractFactory()

        response = client.get(reverse("contract-list"))

        assert response.status_code == 200
        body = response.json()
        assert [c["contract_id"] for c in body] == [str(second.id), str(first.id)]

    def test_summary_shape_and_null_overall_risk_score_for_unscored_contract(self, client):
        contract = ContractFactory()
        ClauseFactory(contract=contract)

        response = client.get(reverse("contract-list"))

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        entry = body[0]
        assert entry["contract_id"] == str(contract.id)
        assert entry["engagement_id"] == contract.engagement_id
        assert entry["razorpay_reference_type"] == contract.razorpay_reference_type
        assert entry["overall_risk_score"] is None
        assert entry["needs_human_review_count"] == 0
        assert "created_at" in entry

    def test_empty_project_returns_empty_list_not_an_error(self, client):
        response = client.get(reverse("contract-list"))

        assert response.status_code == 200
        assert response.json() == []


class TestContractReasoningChainAPIView:
    """Task 4.2 / spec: api/reasoning-chain."""

    def test_every_clause_included_regardless_of_state(self, client):
        contract = ContractFactory()
        ClauseFactory(contract=contract, sequence_index=0)
        needs_review_clause = ClauseFactory(
            contract=contract, sequence_index=1, clause_type="needs_human_review"
        )
        scored_clause = ClauseFactory(contract=contract, sequence_index=2)
        RiskAssessmentFactory(clause=scored_clause, severity=SeverityChoices.HIGH)

        url = reverse("contract-reasoning-chain", kwargs={"contract_id": contract.id})
        response = client.get(url)

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 3
        assert [entry["sequence_index"] for entry in body] == [0, 1, 2]
        assert body[1]["clause_id"] == str(needs_review_clause.id)
        assert body[1]["classification_needs_human_review"] is True

    def test_empty_platform_evidence_list_is_present_not_omitted(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(contract=contract, sequence_index=0)
        ExtractedTermFactory(clause=clause, term_type=TermType.PAYOUT_FREQUENCY)

        url = reverse("contract-reasoning-chain", kwargs={"contract_id": contract.id})
        response = client.get(url)

        body = response.json()
        assert body[0]["platform_evidence"] == []

    def test_platform_evidence_present_when_a_mismatch_flag_is_linked(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(contract=contract, sequence_index=0)
        term = ExtractedTermFactory(clause=clause, term_type=TermType.PAYOUT_FREQUENCY)
        flag = MismatchFlagFactory(extracted_term=term)

        url = reverse("contract-reasoning-chain", kwargs={"contract_id": contract.id})
        response = client.get(url)

        body = response.json()
        assert len(body[0]["platform_evidence"]) == 1
        evidence = body[0]["platform_evidence"][0]
        assert evidence["mismatch_id"] == str(flag.id)
        assert evidence["clause_id"] == str(clause.id)

    def test_null_risk_assessment_for_unscored_clause(self, client):
        contract = ContractFactory()
        ClauseFactory(contract=contract, sequence_index=0)

        url = reverse("contract-reasoning-chain", kwargs={"contract_id": contract.id})
        response = client.get(url)

        body = response.json()
        assert body[0]["risk_assessment"] is None

    def test_risk_assessment_present_for_scored_clause(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(contract=contract, sequence_index=0)
        RiskAssessmentFactory(clause=clause, severity=SeverityChoices.CRITICAL)

        url = reverse("contract-reasoning-chain", kwargs={"contract_id": contract.id})
        response = client.get(url)

        body = response.json()
        assert body[0]["risk_assessment"]["severity"] == "critical"

    def test_unknown_contract_id_returns_404(self, client):
        url = reverse("contract-reasoning-chain", kwargs={"contract_id": uuid.uuid4()})

        response = client.get(url)

        assert response.status_code == 404

    def test_verified_platform_records_appear_in_the_live_response(self, client):
        """Task 1.2 / spec: reporting/confirmed-platform-evidence."""
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract, sequence_index=0)
        ExtractedTermFactory(clause=clause, term_type=TermType.PAYOUT_FREQUENCY)
        payout_record = PlatformRecordFactory(
            contract=contract, record_type=PlatformRecordType.PAYOUT
        )

        url = reverse("contract-reasoning-chain", kwargs={"contract_id": contract.id})
        response = client.get(url)

        assert response.status_code == 200
        body = response.json()
        assert len(body[0]["verified_platform_records"]) == 1
        confirmed = body[0]["verified_platform_records"][0]
        assert confirmed["id"] == str(payout_record.id)
        assert confirmed["record_type"] == "payout"
        assert confirmed["razorpay_id"] == payout_record.razorpay_id

    def test_verified_platform_records_empty_when_no_platform_data_exists(self, client):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract, sequence_index=0)
        ExtractedTermFactory(clause=clause, term_type=TermType.PAYOUT_FREQUENCY)

        url = reverse("contract-reasoning-chain", kwargs={"contract_id": contract.id})
        response = client.get(url)

        body = response.json()
        assert body[0]["verified_platform_records"] == []

    def test_verified_platform_records_empty_when_a_mismatch_is_linked(self, client):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract, sequence_index=0)
        term = ExtractedTermFactory(clause=clause, term_type=TermType.PAYOUT_FREQUENCY)
        MismatchFlagFactory(extracted_term=term)
        PlatformRecordFactory(contract=contract, record_type=PlatformRecordType.PAYOUT)

        url = reverse("contract-reasoning-chain", kwargs={"contract_id": contract.id})
        response = client.get(url)

        body = response.json()
        assert len(body[0]["platform_evidence"]) == 1
        assert body[0]["verified_platform_records"] == []


class TestGuardrailVerificationAPIView:
    """Task 4.3 / spec: api/guardrail-verification."""

    def test_passing_scan_reports_passed_true_with_no_violations(self, client):
        fake_result = GuardrailScanResult(
            passed=True,
            scanned_files=[
                "/project/razorpay_integration/client.py",
                "/project/razorpay_integration/services.py",
            ],
            violations=[],
        )
        with patch("reporting.selectors.scan_razorpay_guardrail", return_value=fake_result):
            response = client.get(reverse("guardrail-verification"))

        assert response.status_code == 200
        body = response.json()
        assert body["passed"] is True
        assert body["scanned_files"] == fake_result.scanned_files
        assert body["violations"] == []

    def test_failing_scan_reports_violation_evidence(self, client):
        fake_result = GuardrailScanResult(
            passed=False,
            scanned_files=["/project/razorpay_integration/client.py"],
            violations=[
                GuardrailViolation(
                    file="/project/razorpay_integration/client.py",
                    line=42,
                    matched_call="sdk_client.post",
                )
            ],
        )
        with patch("reporting.selectors.scan_razorpay_guardrail", return_value=fake_result):
            response = client.get(reverse("guardrail-verification"))

        assert response.status_code == 200
        body = response.json()
        assert body["passed"] is False
        assert body["violations"][0]["file"] == "/project/razorpay_integration/client.py"
        assert body["violations"][0]["line"] == 42
        assert body["violations"][0]["matched_call"] == "sdk_client.post"

    def test_two_consecutive_requests_each_independently_compute_the_scan(self, client):
        """Spec scenario: reflects current source, not a cached claim."""
        call_results = [
            GuardrailScanResult(passed=True, scanned_files=["a.py"], violations=[]),
            GuardrailScanResult(passed=True, scanned_files=["a.py"], violations=[]),
        ]
        with patch(
            "reporting.selectors.scan_razorpay_guardrail", side_effect=call_results
        ) as mock_scan:
            first = client.get(reverse("guardrail-verification"))
            second = client.get(reverse("guardrail-verification"))

        assert first.json() == second.json()
        assert mock_scan.call_count == 2

    def test_default_scan_of_real_production_files_passes(self, client):
        """No mock: confirms the endpoint calls the real live scan end-to-end."""
        response = client.get(reverse("guardrail-verification"))

        assert response.status_code == 200
        body = response.json()
        assert body["passed"] is True
        assert body["violations"] == []
        assert len(body["scanned_files"]) == 2
