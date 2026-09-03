"""Tests for the `report_contract` management command (tasks 8.1-8.3)."""

from __future__ import annotations

import io
import json
import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.tests.factories import AuditLogEntryFactory, ExtractedTermFactory
from razorpay_integration.tests.factories import MismatchFlagFactory
from risk_scoring.models import SeverityChoices
from risk_scoring.tests.factories import RiskAssessmentFactory

pytestmark = pytest.mark.django_db


def _build_scored_contract():
    contract = ContractFactory()
    flagged_clause = ClauseFactory(contract=contract, clause_text="Vendor bears all risk here.")
    RiskAssessmentFactory(
        clause=flagged_clause,
        severity=SeverityChoices.HIGH,
        asymmetry_score=0.6,
        explanation="Vendor bears the full risk under this clause.",
        suggested_rewrite="Share the risk more evenly.",
    )
    review_clause = ClauseFactory(contract=contract, clause_text="Ambiguous boilerplate text.")
    RiskAssessmentFactory(
        clause=review_clause,
        severity=SeverityChoices.NEEDS_HUMAN_REVIEW,
        asymmetry_score=0.0,
        explanation="clause was not confidently classified; scoring deferred to human review",
        suggested_rewrite=None,
    )
    term = ExtractedTermFactory(clause=flagged_clause)
    MismatchFlagFactory(extracted_term=term)
    AuditLogEntryFactory(contract=contract, clause=None, stage=1)
    AuditLogEntryFactory(contract=contract, clause=flagged_clause, stage=2)
    return contract


def _run_command_json(contract_id) -> dict:
    out = io.StringIO()
    call_command("report_contract", f"--contract-id={contract_id}", "--format=json", stdout=out)
    return json.loads(out.getvalue())


class TestCliJsonMatchesApiJson:
    """Task 8.1 / spec: Identical content between API and CLI."""

    def test_cli_json_output_equals_api_json_body_field_for_field(self, client):
        contract = _build_scored_contract()

        cli_payload = _run_command_json(contract.id)

        report_response = client.get(
            reverse("contract-report", kwargs={"contract_id": contract.id})
        )
        audit_response = client.get(
            reverse("contract-audit-trail", kwargs={"contract_id": contract.id})
        )

        assert cli_payload["report"] == report_response.json()
        assert cli_payload["audit_trail"] == audit_response.json()

    def test_defaults_to_json_format(self, client):
        contract = _build_scored_contract()
        out = io.StringIO()

        call_command("report_contract", f"--contract-id={contract.id}", stdout=out)

        payload = json.loads(out.getvalue())
        assert "report" in payload
        assert "audit_trail" in payload


class TestMarkdownFormatMatchesJsonContent:
    """Task 8.2 / spec: Markdown rendering matches JSON content."""

    def test_every_clause_mismatch_and_score_in_json_appears_in_markdown(self):
        contract = _build_scored_contract()

        json_out = io.StringIO()
        call_command(
            "report_contract", f"--contract-id={contract.id}", "--format=json", stdout=json_out
        )
        json_payload = json.loads(json_out.getvalue())["report"]

        md_out = io.StringIO()
        call_command(
            "report_contract", f"--contract-id={contract.id}", "--format=md", stdout=md_out
        )
        markdown = md_out.getvalue()

        assert str(json_payload["overall_risk_score"]) in markdown
        for clause in json_payload["flagged_clauses"]:
            assert clause["clause_id"] in markdown
            assert clause["severity"] in markdown
            assert clause["explanation"] in markdown
        for mismatch in json_payload["platform_mismatches"]:
            assert mismatch["mismatch_id"] in markdown
            assert mismatch["description"] in markdown
        for review_clause in json_payload["needs_human_review_clauses"]:
            assert review_clause["clause_id"] in markdown
            assert review_clause["explanation"] in markdown


class TestUnsupportedFormatRejectedCleanly:
    """Task 8.3 / spec: Unsupported format is rejected cleanly."""

    def test_bogus_format_raises_command_error_before_any_output(self):
        contract = _build_scored_contract()
        out = io.StringIO()

        with pytest.raises(CommandError):
            call_command(
                "report_contract",
                f"--contract-id={contract.id}",
                "--format=bogus",
                stdout=out,
            )

        assert out.getvalue() == ""

    def test_bogus_format_rejected_even_for_an_unknown_contract_id(self):
        """Format is validated before the contract lookup - no partial output either way."""
        out = io.StringIO()

        with pytest.raises(CommandError):
            call_command(
                "report_contract",
                f"--contract-id={uuid.uuid4()}",
                "--format=bogus",
                stdout=out,
            )

        assert out.getvalue() == ""
