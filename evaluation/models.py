"""Models for the `evaluation` app.

`evaluation` owns the two entities this phase adds: a human/rubric-derived
ground-truth label (`EvalLabel`) and the persisted result of one scoring
pass (`EvalRun`). Fields/constraints/simple `clean()`-level validation only,
per project convention - no cross-model orchestration here. See design.md
(add-evaluation-harness) - Decisions.
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from contracts.models import Clause, Contract


class EvalLabelType(models.TextChoices):
    """The two kinds of ground-truth label this app records.

    `risk_severity` covers both per-clause rubric labels (`clause` set) and
    the per-contract `overall_risk_tier` floor-rule label (`clause` null) -
    see design.md - Decisions ("clause: FK(Clause, null=True) (null for
    contract-level labels such as overall_risk_tier)").
    """

    RISK_SEVERITY = "risk_severity", "Risk severity"
    MISMATCH_PRESENT = "mismatch_present", "Mismatch present"


class EvalLabel(models.Model):
    """One ground-truth label - human-authored or rubric-derived - for scoring.

    `ground_truth_value` holds the rubric fields per `label_type`:
    - `risk_severity` (clause-level): `clause_type`, `risky`, `severity`
      (1-5), `rationale`, `needs_human_review`.
    - `risk_severity` (contract-level, `clause` null): `overall_risk_tier`.
    - `mismatch_present`: `mismatch_type` (a `MismatchType` value, or `None`
      for an expected `no_mismatch`) and `expected_verdict`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="eval_labels")
    clause = models.ForeignKey(
        Clause, on_delete=models.CASCADE, related_name="eval_labels", null=True, blank=True
    )
    label_type = models.CharField(max_length=32, choices=EvalLabelType.choices)
    ground_truth_value = models.JSONField(default=dict)
    annotator = models.CharField(max_length=128, default="synthetic-rubric-v1")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"EvalLabel({self.label_type}) for contract {self.contract_id}"

    def clean(self) -> None:
        if self.label_type == EvalLabelType.MISMATCH_PRESENT and self.clause_id is None:
            raise ValidationError(
                {"clause": "clause is required when label_type=mismatch_present."}
            )


class EvalRun(models.Model):
    """One persisted result of running `evaluation.services.run_eval`.

    Every metric that risks hiding a real failure mode is kept as its own
    field/JSON key rather than folded into a single score - see design.md -
    Goals ("Keep every metric that risks hiding a real failure mode reported
    separately"). `fixture_version` is not itemized in design.md's field
    list but is required by
    specs/evaluation/razorpay-fixtures/spec.md ("EvalRun records the fixture
    version used") - added here to satisfy that requirement without
    inventing a second model.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run_at = models.DateTimeField(auto_now_add=True)
    dataset_version = models.CharField(max_length=64)
    fixture_version = models.CharField(max_length=64)
    precision_recall_f1 = models.JSONField(default=dict)
    severity_calibration_score = models.FloatField()
    cost_report = models.JSONField(default=dict)
    false_positive_cost_note = models.TextField()
    pipeline_version = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=255)

    class Meta:
        ordering = ["-run_at"]

    def __str__(self) -> str:
        return f"EvalRun {self.id} ({self.dataset_version}, {self.run_at})"
