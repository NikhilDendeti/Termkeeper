"""Django-template views for the `report_ui` app.

Every view here is thin: look up the Contract (404 on a miss), call one or
two selectors, and render a template - no aggregation, no formatting
decisions beyond what the template layer does. See design.md
(add-report-ui) - Decisions.
"""

from __future__ import annotations

import uuid

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from contracts import selectors as contracts_selectors
from contracts.models import Contract
from pipeline import selectors as pipeline_selectors
from reporting import selectors as reporting_selectors


def _get_contract_or_404(contract_id: uuid.UUID) -> Contract:
    try:
        return contracts_selectors.get_contract(contract_id=contract_id)
    except Contract.DoesNotExist as exc:
        raise Http404(f"No Contract found with id {contract_id}") from exc


def contract_report_view(request: HttpRequest, contract_id: uuid.UUID) -> HttpResponse:
    """Render a contract's clause-by-clause reasoning chain.

    See specs/report-ui/reasoning-chain-view/spec.md.
    """
    contract = _get_contract_or_404(contract_id)
    report = reporting_selectors.get_contract_report(contract=contract)
    clause_chains = reporting_selectors.get_contract_reasoning_chain(contract=contract)
    return render(
        request,
        "report_ui/contract_report.html",
        {"contract": contract, "report": report, "clause_chains": clause_chains},
    )


def contract_audit_log_view(request: HttpRequest, contract_id: uuid.UUID) -> HttpResponse:
    """Render a contract's complete audit trail, in stage order.

    See specs/report-ui/audit-log-view/spec.md.
    """
    contract = _get_contract_or_404(contract_id)
    entries = pipeline_selectors.get_audit_trail(contract=contract)
    return render(
        request,
        "report_ui/contract_audit_log.html",
        {"contract": contract, "entries": entries},
    )


def guardrail_verification_view(request: HttpRequest) -> HttpResponse:
    """Render the live static-scan proof that razorpay_integration issues no write calls.

    See specs/report-ui/guardrail-verification-view/spec.md.
    """
    result = reporting_selectors.scan_razorpay_guardrail()
    return render(request, "report_ui/guardrail_verification.html", {"result": result})
