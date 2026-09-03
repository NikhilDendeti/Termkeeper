"""Model-level tests for EvalLabel (task 1.2)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from contracts.tests.factories import ContractFactory
from evaluation.models import EvalLabel, EvalLabelType

pytestmark = pytest.mark.django_db


class TestMismatchPresentRequiresClause:
    """Requirement: EvalLabel.label_type=mismatch_present requires clause non-null."""

    def test_mismatch_present_with_no_clause_fails_validation(self):
        contract = ContractFactory()
        label = EvalLabel(
            contract=contract,
            clause=None,
            label_type=EvalLabelType.MISMATCH_PRESENT,
            ground_truth_value={"mismatch_type": "cadence_mismatch"},
        )
        with pytest.raises(ValidationError):
            label.full_clean()

    def test_risk_severity_with_no_clause_is_valid(self):
        contract = ContractFactory()
        label = EvalLabel(
            contract=contract,
            clause=None,
            label_type=EvalLabelType.RISK_SEVERITY,
            ground_truth_value={"overall_risk_tier": "low"},
        )
        label.full_clean()  # does not raise
