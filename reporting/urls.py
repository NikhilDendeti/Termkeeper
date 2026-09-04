"""URL routes for the `reporting` app.

See design.md (add-risk-scoring-report) - "urls.py: contracts/<uuid:
contract_id>/report/ and contracts/<uuid:contract_id>/audit-trail/,
included from the project URLConf." The three routes below (contract list,
reasoning chain, guardrail verification) added in add-react-frontend - see
that change's design.md (api/contract-listing, api/reasoning-chain,
api/guardrail-verification), following the same naming convention.
"""

from django.urls import path

from reporting.views import (
    ContractAuditTrailAPIView,
    ContractDocumentAPIView,
    ContractListAPIView,
    ContractReasoningChainAPIView,
    ContractReportAPIView,
    GuardrailVerificationAPIView,
)

urlpatterns = [
    path(
        "contracts/",
        ContractListAPIView.as_view(),
        name="contract-list",
    ),
    path(
        "contracts/<uuid:contract_id>/report/",
        ContractReportAPIView.as_view(),
        name="contract-report",
    ),
    path(
        "contracts/<uuid:contract_id>/document/",
        ContractDocumentAPIView.as_view(),
        name="contract-document",
    ),
    path(
        "contracts/<uuid:contract_id>/audit-trail/",
        ContractAuditTrailAPIView.as_view(),
        name="contract-audit-trail",
    ),
    path(
        "contracts/<uuid:contract_id>/reasoning-chain/",
        ContractReasoningChainAPIView.as_view(),
        name="contract-reasoning-chain",
    ),
    path(
        "guardrail-verification/",
        GuardrailVerificationAPIView.as_view(),
        name="guardrail-verification",
    ),
]
