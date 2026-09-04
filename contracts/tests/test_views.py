"""Tests for contracts.views.ContractCreateAPIView.

See openspec/changes/add-contract-upload/specs/contracts/upload-api/spec.md
and tasks.md (tasks 1.1, 1.2).
"""

from __future__ import annotations

import json

import pytest
from django.urls import reverse

from contracts.management.commands.ingest_contract import Command as IngestContractCommand
from contracts.models import Contract

pytestmark = pytest.mark.django_db


def _post(client, payload):
    return client.post(
        reverse("contract-create"),
        data=json.dumps(payload),
        content_type="application/json",
    )


_VALID_PAYLOAD = {
    "raw_text": "This agreement shall govern payment terms between the parties.",
    "engagement_id": "ENG-UPLOAD-001",
    "razorpay_reference_type": "payout",
    "razorpay_reference_id": "pout_UPLOAD123",
    "source_filename": "uploaded.txt",
}


class TestContractCreateAPIView:
    """Task 1.1 / spec: Contract creation endpoint."""

    def test_valid_submission_creates_contract_and_returns_id_with_201(self, client):
        response = _post(client, _VALID_PAYLOAD)

        assert response.status_code == 201
        body = response.json()
        assert "contract_id" in body

        contract = Contract.objects.get(id=body["contract_id"])
        assert contract.raw_text == _VALID_PAYLOAD["raw_text"]
        assert contract.engagement_id == "ENG-UPLOAD-001"
        assert contract.razorpay_reference_type == "payout"
        assert contract.razorpay_reference_id == "pout_UPLOAD123"
        assert contract.source_filename == "uploaded.txt"

    def test_valid_submission_without_source_filename_still_succeeds(self, client):
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "source_filename"}

        response = _post(client, payload)

        assert response.status_code == 201

    @pytest.mark.parametrize(
        "missing_field",
        ["raw_text", "engagement_id", "razorpay_reference_type", "razorpay_reference_id"],
    )
    def test_missing_required_field_rejected_with_400_and_field_error(self, client, missing_field):
        before_count = Contract.objects.count()
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != missing_field}

        response = _post(client, payload)

        assert response.status_code == 400
        body = response.json()
        assert missing_field in body
        assert Contract.objects.count() == before_count

    def test_empty_raw_text_rejected_with_400(self, client):
        before_count = Contract.objects.count()
        payload = {**_VALID_PAYLOAD, "raw_text": "   "}

        response = _post(client, payload)

        assert response.status_code == 400
        assert Contract.objects.count() == before_count

    def test_invalid_razorpay_reference_type_rejected_with_400(self, client):
        payload = {**_VALID_PAYLOAD, "razorpay_reference_type": "not_a_real_type"}

        response = _post(client, payload)

        assert response.status_code == 400
        body = response.json()
        assert "razorpay_reference_type" in body


class TestUrlResolves:
    def test_contract_create_url_resolves(self):
        url = reverse("contract-create")
        assert url.endswith("/contracts/create/")


class TestEndpointMatchesCliPath:
    """Task 1.2 / spec: Endpoint reuses existing validation, does not duplicate it."""

    def test_endpoint_and_ingest_command_produce_equivalent_contract_state(
        self, client, tmp_path
    ):
        raw_text = "Vendor shall invoice Client monthly under net 30 terms."

        # Via the new HTTP endpoint.
        api_payload = {
            "raw_text": raw_text,
            "engagement_id": "ENG-PARITY-API",
            "razorpay_reference_type": "subscription",
            "razorpay_reference_id": "sub_PARITY001",
            "source_filename": "parity.txt",
        }
        response = _post(client, api_payload)
        assert response.status_code == 201
        api_contract = Contract.objects.get(id=response.json()["contract_id"])

        # Via the existing `ingest_contract` management command, same inputs
        # (bar identifiers that must be unique/positional).
        contract_file = tmp_path / "parity.txt"
        contract_file.write_text(raw_text, encoding="utf-8")

        command = IngestContractCommand()
        command.handle(
            file_path=str(contract_file),
            engagement_id="ENG-PARITY-CLI",
            razorpay_reference_type="subscription",
            razorpay_reference_id="sub_PARITY002",
            source_filename="parity.txt",
        )
        cli_contract = Contract.objects.get(engagement_id="ENG-PARITY-CLI")

        # Equivalent Contract state: same raw text, same reference type, same
        # source filename, both valid and persisted - no endpoint-specific
        # validation rule diverges from the CLI path.
        assert api_contract.raw_text == cli_contract.raw_text
        assert api_contract.razorpay_reference_type == cli_contract.razorpay_reference_type
        assert api_contract.source_filename == cli_contract.source_filename
        assert api_contract.needs_human_review == cli_contract.needs_human_review is False
