"""Models for the `risk_scoring` app.

`risk_scoring` owns the one entity pipeline stage 5 produces: the current
risk assessment for a classified Clause (`RiskAssessment`). Fields/
constraints/simple validation only, per HackSoft convention - no business
logic on the model. See design.md (add-risk-scoring-report) - Decisions.
"""

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from contracts.models import Clause


class SeverityChoices(models.TextChoices):
    """Fixed 5-label severity taxonomy a RiskAssessment can carry.

    See specs/risk-scoring/clause-severity/spec.md (Requirement: Fixed
    severity taxonomy).
    """

    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"
    NEEDS_HUMAN_REVIEW = "needs_human_review", "Needs human review"


class RiskAssessment(models.Model):
    """The one current risk assessment for a Clause.

    `clause` is a `OneToOneField`, not a plain `ForeignKey`: exactly one
    *current* RiskAssessment exists per Clause, and re-running stage 5 is an
    update-or-create, not an append - see design.md - Decisions
    ("RiskAssessment.clause is a OneToOneField, not a plain ForeignKey").

    `linked_mismatch_flag_ids` stores each linked MismatchFlag's id (as a
    string) in a `JSONField`, not the `django.contrib.postgres.fields.
    ArrayField` design.md names for this field: this project's database is
    SQLite only (see config/settings/base.py - "Database - SQLite only,
    deliberately"), and `ArrayField` cannot even be imported without the
    `psycopg` driver, which this project does not declare as a dependency
    (see pyproject.toml). A `JSONField` list of id strings satisfies every
    behavioral requirement this field exists for - see
    specs/risk-scoring/clause-severity/spec.md ("Mismatch linkage recorded
    on the assessment") - without requiring a database engine this project
    deliberately does not use.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clause = models.OneToOneField(
        Clause, on_delete=models.CASCADE, related_name="risk_assessment"
    )
    severity = models.CharField(max_length=32, choices=SeverityChoices.choices)
    asymmetry_score = models.FloatField(
        validators=[MinValueValidator(-1.0), MaxValueValidator(1.0)]
    )
    explanation = models.TextField()
    suggested_rewrite = models.TextField(null=True, blank=True)
    linked_mismatch_flag_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(asymmetry_score__gte=-1) & Q(asymmetry_score__lte=1),
                name="risk_assessment_asymmetry_score_range",
            )
        ]

    def __str__(self) -> str:
        return f"RiskAssessment({self.severity}) for clause {self.clause_id}"
