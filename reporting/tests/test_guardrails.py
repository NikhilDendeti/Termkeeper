"""Standing guardrail tests for the reporting surface (task 9).

9.1: repeated report/audit-trail/report_contract invocations leave every
row count unchanged.
9.2: a static scan (matching phase 2's client.py scan pattern - see
razorpay_integration/tests/test_client.py) confirming none of reporting's
own source files call a write method on a Django model.
"""

from __future__ import annotations

import ast
import inspect
import io

import pytest
from django.core.management import call_command
from django.urls import reverse

from contracts import selectors as contracts_selectors
from contracts.models import Clause, Contract
from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline import selectors as pipeline_selectors
from pipeline.models import ExtractedTerm
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration import selectors as razorpay_selectors
from razorpay_integration.models import MismatchFlag, PlatformRecord
from razorpay_integration.tests.factories import MismatchFlagFactory, PlatformRecordFactory
from reporting import selectors as reporting_selectors
from reporting import views as reporting_views
from reporting.management.commands import report_contract as report_contract_command
from risk_scoring import selectors as risk_scoring_selectors
from risk_scoring.models import RiskAssessment, SeverityChoices
from risk_scoring.tests.factories import RiskAssessmentFactory

pytestmark = pytest.mark.django_db


def _snapshot_counts() -> dict[str, int]:
    return {
        "Contract": Contract.objects.count(),
        "Clause": Clause.objects.count(),
        "ExtractedTerm": ExtractedTerm.objects.count(),
        "PlatformRecord": PlatformRecord.objects.count(),
        "MismatchFlag": MismatchFlag.objects.count(),
        "RiskAssessment": RiskAssessment.objects.count(),
    }


class TestReadOnlyReportSurfaceLeavesRowCountsUnchanged:
    """Task 9.1 / spec: Repeated report requests leave data unchanged."""

    def test_repeated_invocations_do_not_change_any_row_count(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(contract=contract)
        RiskAssessmentFactory(clause=clause, severity=SeverityChoices.HIGH)
        term = ExtractedTermFactory(clause=clause)
        PlatformRecordFactory(contract=contract)
        MismatchFlagFactory(extracted_term=term)

        before = _snapshot_counts()

        report_url = reverse("contract-report", kwargs={"contract_id": contract.id})
        audit_url = reverse("contract-audit-trail", kwargs={"contract_id": contract.id})
        for _ in range(3):
            assert client.get(report_url).status_code == 200
            assert client.get(audit_url).status_code == 200
            out = io.StringIO()
            call_command(
                "report_contract", f"--contract-id={contract.id}", "--format=json", stdout=out
            )
            out_md = io.StringIO()
            call_command(
                "report_contract", f"--contract-id={contract.id}", "--format=md", stdout=out_md
            )

        after = _snapshot_counts()
        assert after == before


# Any call to a method with one of these names, anywhere reachable from
# reporting's own report-surface source, would be a write against the
# database - the report surface must never issue one. See
# razorpay_integration/tests/test_client.py for the precedent this mirrors.
_FORBIDDEN_WRITE_METHOD_NAMES = frozenset(
    {"save", "create", "update", "delete", "bulk_create", "bulk_update", "get_or_create"}
)


def _called_method_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


class TestReportSurfaceSourceGuardrail:
    """Task 9.2: no write-verb call anywhere reachable from the report surface's source.

    Covers `reporting`'s own three report-surface modules plus every
    selector module they call into (`contracts`, `pipeline`,
    `razorpay_integration`, `risk_scoring`) - matching phase 2's
    `test_client.py` scan pattern, extended to the full reachable set of
    modules `get_contract_report`/the views/the command import.
    """

    @pytest.mark.parametrize(
        "module",
        [
            reporting_selectors,
            reporting_views,
            report_contract_command,
            contracts_selectors,
            pipeline_selectors,
            razorpay_selectors,
            risk_scoring_selectors,
        ],
    )
    def test_module_source_contains_no_write_verb_calls(self, module):
        source = inspect.getsource(module)

        called_names = _called_method_names(source)

        forbidden_calls_found = called_names & _FORBIDDEN_WRITE_METHOD_NAMES
        assert forbidden_calls_found == set(), (
            f"{module.__name__} calls forbidden write-verb method(s): "
            f"{forbidden_calls_found!r} - the report surface must be read-only."
        )
