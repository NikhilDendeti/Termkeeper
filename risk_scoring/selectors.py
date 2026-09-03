"""Read-path selector functions for the `risk_scoring` app.

Every non-trivial read goes through a function here per project convention.
"""

from __future__ import annotations

from django.db.models import QuerySet

from contracts.models import Clause, Contract
from razorpay_integration.models import MismatchFlag
from risk_scoring.models import RiskAssessment


def get_risk_assessment_for_clause(*, clause: Clause) -> RiskAssessment | None:
    """Return the current RiskAssessment for `clause`, or None if unscored."""
    return RiskAssessment.objects.filter(clause=clause).first()


def list_risk_assessments_for_contract(*, contract: Contract) -> QuerySet[RiskAssessment]:
    """List every current RiskAssessment for a Contract's clauses, in clause order."""
    return (
        RiskAssessment.objects.filter(clause__contract=contract)
        .select_related("clause")
        .order_by("clause__sequence_index")
    )


def get_linked_mismatch_flags(*, clause: Clause) -> QuerySet[MismatchFlag]:
    """List every MismatchFlag reachable from `clause` via its ExtractedTerm rows.

    MismatchFlag has no direct FK to Clause (razorpay_integration:
    `extracted_term: FK(pipeline.ExtractedTerm)`) - linkage is resolved as
    `MismatchFlag.objects.filter(extracted_term__clause=clause)`, evaluated
    at call time. See design.md - Decisions ("Mismatch linkage query").
    """
    return MismatchFlag.objects.filter(extracted_term__clause=clause).order_by("created_at")
