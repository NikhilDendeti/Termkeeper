"""DRF views for the `reporting` app.

Every view is thin: look up the Contract (404 on a miss) where relevant,
then hand off to one selector - no business logic lives here. See
design.md (add-risk-scoring-report) - "reporting exposes a thin APIView,
not a ViewSet." `ContractListAPIView`, `ContractReasoningChainAPIView`, and
`GuardrailVerificationAPIView` added in add-react-frontend - see that
change's design.md (api/contract-listing, api/reasoning-chain,
api/guardrail-verification).
"""

from __future__ import annotations

import uuid

from django.http import Http404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from contracts import selectors as contracts_selectors
from contracts.models import Contract
from reporting import selectors as reporting_selectors
from reporting.serializers import (
    AuditLogEntrySerializer,
    ClauseReasoningChainSerializer,
    ContractReportSerializer,
    ContractSummarySerializer,
    GuardrailScanResultSerializer,
)


def _get_contract_or_404(contract_id: uuid.UUID) -> Contract:
    try:
        return contracts_selectors.get_contract(contract_id=contract_id)
    except Contract.DoesNotExist as exc:
        raise Http404(f"No Contract found with id {contract_id}") from exc


class ContractReportAPIView(APIView):
    """GET a contract's aggregate risk report.

    See specs/reporting/report-api/spec.md (Requirement: Retrieve-only
    report endpoint).
    """

    def get(self, request: Request, contract_id: uuid.UUID) -> Response:
        contract = _get_contract_or_404(contract_id)
        report = reporting_selectors.get_contract_report(contract=contract)
        serializer = ContractReportSerializer(instance=report)
        return Response(serializer.data)


class ContractAuditTrailAPIView(APIView):
    """GET a contract's full audit trail, oldest first.

    See specs/reporting/report-api/spec.md (Requirement: Audit trail
    exposed through the same surface).
    """

    def get(self, request: Request, contract_id: uuid.UUID) -> Response:
        contract = _get_contract_or_404(contract_id)
        entries = reporting_selectors.get_full_audit_trail(contract=contract)
        serializer = AuditLogEntrySerializer(instance=entries, many=True)
        return Response(serializer.data)


class ContractListAPIView(APIView):
    """GET every ingested Contract's headline summary, newest-created first.

    See specs/api/contract-listing/spec.md (Requirement: Contract list
    endpoint).
    """

    def get(self, request: Request) -> Response:
        summaries = reporting_selectors.list_contract_summaries()
        serializer = ContractSummarySerializer(instance=summaries, many=True)
        return Response(serializer.data)


class ContractReasoningChainAPIView(APIView):
    """GET a contract's full per-clause reasoning chain, in sequence order.

    See specs/api/reasoning-chain/spec.md (Requirement: Reasoning-chain
    endpoint).
    """

    def get(self, request: Request, contract_id: uuid.UUID) -> Response:
        contract = _get_contract_or_404(contract_id)
        chains = reporting_selectors.get_contract_reasoning_chain(contract=contract)
        serializer = ClauseReasoningChainSerializer(instance=chains, many=True)
        return Response(serializer.data)


class GuardrailVerificationAPIView(APIView):
    """GET the live Razorpay-integration write-call guardrail scan result.

    Runs the scan fresh on every request - never cached or stored - see
    specs/api/guardrail-verification/spec.md (Scenario: Result reflects
    current source, not a cached claim).
    """

    def get(self, request: Request) -> Response:
        result = reporting_selectors.scan_razorpay_guardrail()
        serializer = GuardrailScanResultSerializer(instance=result)
        return Response(serializer.data)
