"""Tests for pipeline.views.AnalyzeContractAPIView.

See openspec/changes/add-contract-upload/specs/pipeline/analyze-api/spec.md
and tasks.md (tasks 2.1, 2.2).

`pipeline.services.run_pipeline` is mocked directly in every test here - the
point of these tests is that the ENDPOINT's lookup, success-response, and
exception-handling behavior is correct, not re-testing `run_pipeline`'s own
internals (already covered by pipeline/tests/test_orchestration.py). No real
network/LLM call is made.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from django.urls import reverse

from contracts.models import Clause
from contracts.tests.factories import ClauseFactory, ContractFactory
from risk_scoring.models import SeverityChoices
from risk_scoring.tests.factories import RiskAssessmentFactory

pytestmark = pytest.mark.django_db


def _analyze_url(contract_id):
    return reverse("contract-analyze", kwargs={"contract_id": contract_id})


class TestAnalyzeContractAPIViewSuccess:
    """Task 2.1 / spec: Synchronous pipeline trigger endpoint."""

    def test_successful_analysis_returns_the_aggregate_report_shape(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(contract=contract, clause_type="termination")
        RiskAssessmentFactory(clause=clause, severity=SeverityChoices.HIGH, asymmetry_score=0.7)

        with patch("pipeline.services.run_pipeline") as mock_run_pipeline:
            response = client.post(_analyze_url(contract.id))

        mock_run_pipeline.assert_called_once_with(contract=contract)
        assert response.status_code == 200
        body = response.json()
        assert body["contract_id"] == str(contract.id)
        assert body["overall_risk_score"] == 0.75
        assert "flagged_clauses" in body
        assert "platform_mismatches" in body
        assert "needs_human_review_clauses" in body
        assert "severity_breakdown_by_clause_type" in body
        assert body["flagged_clauses"][0]["severity"] == "high"

    def test_response_shape_matches_the_existing_report_endpoint(self, client):
        """Same shape the existing GET report endpoint already returns."""
        contract = ContractFactory()
        clause = ClauseFactory(contract=contract)
        RiskAssessmentFactory(clause=clause, severity=SeverityChoices.MEDIUM)

        with patch("pipeline.services.run_pipeline"):
            analyze_response = client.post(_analyze_url(contract.id))

        report_response = client.get(reverse("contract-report", kwargs={"contract_id": contract.id}))

        assert analyze_response.status_code == 200
        assert report_response.status_code == 200
        assert analyze_response.json() == report_response.json()


class TestAnalyzeContractAPIViewUnknownContract:
    """Task 2.1 / spec: Unknown contract returns a clear error."""

    def test_unknown_contract_id_returns_404_and_does_not_run_pipeline(self, client):
        unknown_id = uuid.uuid4()

        with patch("pipeline.services.run_pipeline") as mock_run_pipeline:
            response = client.post(_analyze_url(unknown_id))

        assert response.status_code == 404
        mock_run_pipeline.assert_not_called()


class TestAnalyzeContractAPIViewMidRunFailure:
    """Task 2.2 / spec: Mid-run failure is reported, not silently swallowed."""

    def test_provider_error_mid_run_returns_structured_502_and_preserves_partial_state(
        self, client
    ):
        contract = ContractFactory()
        # Represents partial progress a real run_pipeline would have already
        # persisted before hitting a provider error mid-run (e.g. stage 1
        # succeeded, stage 2 raised).
        persisted_clause = ClauseFactory(contract=contract, sequence_index=0, clause_type=None)

        with patch(
            "pipeline.services.run_pipeline",
            side_effect=Exception("OpenAI provider rate limit exceeded"),
        ):
            response = client.post(_analyze_url(contract.id))

        assert response.status_code == 502
        body = response.json()
        assert body["contract_id"] == str(contract.id)
        assert body["error"] == "OpenAI provider rate limit exceeded"
        assert body["partial_progress"] is True
        assert "detail" in body

        # No already-persisted row is deleted or altered.
        reloaded_clause = Clause.objects.get(id=persisted_clause.id)
        assert reloaded_clause.clause_text == persisted_clause.clause_text
        assert reloaded_clause.sequence_index == persisted_clause.sequence_index
        assert Clause.objects.filter(contract=contract).count() == 1

    def test_bare_500_is_never_returned_on_pipeline_failure(self, client):
        contract = ContractFactory()

        with patch(
            "pipeline.services.run_pipeline",
            side_effect=RuntimeError("unexpected failure"),
        ):
            response = client.post(_analyze_url(contract.id))

        assert response.status_code != 500
        assert response.status_code == 502


class TestUrlResolves:
    def test_contract_analyze_url_resolves(self):
        contract_id = uuid.uuid4()
        url = _analyze_url(contract_id)
        assert str(contract_id) in url
        assert url.endswith("/analyze/")
