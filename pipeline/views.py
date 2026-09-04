"""DRF views for the `pipeline` app.

Thin per project convention: look up the Contract (404 on a miss), call
`pipeline.services.run_pipeline` unmodified, and on success serialize the
resulting report via the *existing* `reporting.serializers.
ContractReportSerializer` - imported, not duplicated. See
openspec/changes/add-contract-upload/design.md (Decisions - "pipeline app
gains an HTTP surface").
"""

from __future__ import annotations

import uuid

from django.http import Http404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from contracts import selectors as contracts_selectors
from contracts.models import Contract
from pipeline import services as pipeline_services
from reporting import selectors as reporting_selectors
from reporting.serializers import ContractReportSerializer


def _get_contract_or_404(contract_id: uuid.UUID) -> Contract:
    """Duplicated from reporting/views.py's `_get_contract_or_404` pattern.

    `pipeline` cannot import this from `reporting` - `reporting` depends on
    `pipeline`, not the reverse - so the small lookup-and-404 helper is
    duplicated here rather than introducing a cycle. See design.md
    (Decisions).
    """
    try:
        return contracts_selectors.get_contract(contract_id=contract_id)
    except Contract.DoesNotExist as exc:
        raise Http404(f"No Contract found with id {contract_id}") from exc


class AnalyzeContractAPIView(APIView):
    """POST to run the existing pipeline against a contract, synchronously.

    See specs/pipeline/analyze-api/spec.md (Requirement: Synchronous
    pipeline trigger endpoint; Requirement: Mid-run failure is reported, not
    silently swallowed or a bare server error).
    """

    def post(self, request: Request, contract_id: uuid.UUID) -> Response:
        contract = _get_contract_or_404(contract_id)

        try:
            pipeline_services.run_pipeline(contract=contract)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see design.md
            return Response(
                {
                    "contract_id": str(contract.id),
                    "error": str(exc),
                    "partial_progress": True,
                    "detail": (
                        "Pipeline stopped partway through. Whatever was "
                        "already analyzed has been saved."
                    ),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        report = reporting_selectors.get_contract_report(contract=contract)
        serializer = ContractReportSerializer(instance=report)
        return Response(serializer.data, status=status.HTTP_200_OK)
