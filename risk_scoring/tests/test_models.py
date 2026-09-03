"""Model-level tests for RiskAssessment (tasks 1.3, 1.4)."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from contracts.tests.factories import ClauseFactory
from risk_scoring.models import RiskAssessment, SeverityChoices
from risk_scoring.tests.factories import RiskAssessmentFactory

pytestmark = pytest.mark.django_db


class TestAsymmetryScoreBoundedByCheckConstraint:
    """Requirement: Bounded asymmetry score (spec: clause-severity)."""

    @pytest.mark.parametrize("out_of_range_score", [-1.5, 1.5, -1.0001, 1.0001])
    def test_out_of_range_asymmetry_score_is_rejected_at_the_database_level(
        self, out_of_range_score
    ):
        clause = ClauseFactory()
        with pytest.raises(IntegrityError), transaction.atomic():
            RiskAssessment.objects.create(
                clause=clause,
                severity=SeverityChoices.MEDIUM,
                asymmetry_score=out_of_range_score,
                explanation="x",
            )

    @pytest.mark.parametrize("boundary_score", [-1.0, 1.0, 0.0])
    def test_boundary_asymmetry_scores_are_accepted(self, boundary_score):
        clause = ClauseFactory()
        assessment = RiskAssessment.objects.create(
            clause=clause,
            severity=SeverityChoices.MEDIUM,
            asymmetry_score=boundary_score,
            explanation="x",
        )
        assert assessment.asymmetry_score == boundary_score


class TestOneAssessmentPerClause:
    """Requirement: Coverage of every classified clause - one assessment per clause."""

    def test_a_second_risk_assessment_cannot_be_created_for_an_already_scored_clause(self):
        clause = ClauseFactory()
        RiskAssessmentFactory(clause=clause)

        with pytest.raises(IntegrityError), transaction.atomic():
            RiskAssessment.objects.create(
                clause=clause,
                severity=SeverityChoices.LOW,
                asymmetry_score=0.1,
                explanation="second attempt",
            )

        assert RiskAssessment.objects.filter(clause=clause).count() == 1
