"""Typed dataclasses and axis taxonomies for synthetic dataset generation and scoring.

Kept separate from `models.py` (Django models) and `services.py`/`selectors.py`
(functions) because these are plain, non-persisted value types shared by
both - see specs/evaluation/synthetic-dataset/spec.md (Requirement:
Five-axis dataset coverage) and design.md - Decisions
("SyntheticContractParams is a typed dataclass").
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from contracts.models import RazorpayReferenceType

# ---------------------------------------------------------------------------
# Five-axis taxonomy (spec: evaluation/synthetic-dataset - Five-axis dataset
# coverage). String values match the spec's literal axis-value spelling
# exactly (including hyphenation) since dataset-coverage tests assert every
# defined value appears at least once.
# ---------------------------------------------------------------------------


class EngagementType(enum.StrEnum):
    FIXED_FEE = "fixed-fee"
    MILESTONE = "milestone"
    RETAINER = "retainer"


class Domain(enum.StrEnum):
    DESIGN = "design"
    DEV = "dev"
    CONTENT = "content"
    CONSULTING = "consulting"


class ClauseSeverityProfile(enum.StrEnum):
    FAIR = "fair"
    MILDLY_ONE_SIDED = "mildly-one-sided"
    DELIBERATELY_EXPLOITATIVE = "deliberately-exploitative"


class PhrasingStyle(enum.StrEnum):
    PLAIN = "plain"
    LEGALESE = "legalese"
    DELIBERATELY_VAGUE = "deliberately-vague"


# razorpay_reference_type reuses contracts.models.RazorpayReferenceType
# (payout/subscription) rather than redefining the same taxonomy twice -
# both Contract and the synthetic-dataset axis need exactly the same two
# values.

_AXIS_ENUMS: dict[str, type[enum.Enum]] = {
    "engagement_type": EngagementType,
    "domain": Domain,
    "clause_severity_profile": ClauseSeverityProfile,
    "phrasing_style": PhrasingStyle,
    "razorpay_reference_type": RazorpayReferenceType,
}


def _validate_choice(field_name: str, value: str, enum_cls: type[enum.Enum]) -> None:
    valid_values = {member.value for member in enum_cls}
    if value not in valid_values:
        raise ValueError(
            f"{field_name}={value!r} is not one of the allowed taxonomy values "
            f"{sorted(valid_values)!r}"
        )


@dataclass(frozen=True)
class SyntheticContractParams:
    """The five axis values plus a seed for one synthetic contract.

    See design.md - Decisions ("SyntheticContractParams is a typed dataclass
    carrying the five axis values plus a seed: int"). Rejects an
    out-of-taxonomy axis value at construction time (task 1.3).
    """

    engagement_type: str
    domain: str
    clause_severity_profile: str
    phrasing_style: str
    razorpay_reference_type: str
    seed: int

    def __post_init__(self) -> None:
        for axis_name, enum_cls in _AXIS_ENUMS.items():
            _validate_choice(axis_name, getattr(self, axis_name), enum_cls)


# ---------------------------------------------------------------------------
# Per-clause ground truth (spec: evaluation/synthetic-dataset - Ground truth
# generated before prose, Per-clause human labeling rubric)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClauseGroundTruth:
    """One synthetic clause's ground truth: numeric terms plus rubric labels.

    Numeric fields (`amount`, `cadence_days`, `notice_period_days`,
    `penalty_pct`) are `None` when not applicable to `clause_type` - only
    the fields a real clause of that type would state are populated.
    """

    clause_type: str
    severity_profile: str
    amount: float | None
    cadence_days: float | None
    notice_period_days: int | None
    penalty_pct: float | None
    risky: bool
    severity: int
    rationale: str
    needs_human_review: bool


@dataclass(frozen=True)
class HeldoutManifest:
    """The committed held-out split manifest for one `dataset_version`.

    `get_heldout_manifest` returns this without comparing `recorded_hash`
    against a freshly computed one - see design.md - Decisions
    ("does not itself raise on mismatch - run_eval does the comparison").
    """

    dataset_version: str
    heldout_engagement_ids: list[str]
    recorded_hash: str


# ---------------------------------------------------------------------------
# Scoring result types (spec: evaluation/scoring-harness)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskSeverityScores:
    precision: float
    recall: float
    f1: float
    human_review_recall: float
    severity_calibration_score: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    scored_clause_count: int
    human_review_clause_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "human_review_recall": self.human_review_recall,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
            "scored_clause_count": self.scored_clause_count,
            "human_review_clause_count": self.human_review_clause_count,
        }


@dataclass(frozen=True)
class MismatchFlagScores:
    precision: float
    recall: float
    true_positives: int
    false_positives: int
    false_negatives: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
        }


@dataclass(frozen=True)
class CostReport:
    minutes_per_dismissed_flag: float
    fp_count: int
    fn_count: int
    fp_cost: float
    fn_cost: float
    fn_to_fp_cost_ratio: float | None
    by_clause_type: dict[str, dict[str, float]] = field(default_factory=dict)
    by_mismatch_type: dict[str, dict[str, float]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "minutes_per_dismissed_flag": self.minutes_per_dismissed_flag,
            "fp_count": self.fp_count,
            "fn_count": self.fn_count,
            "fp_cost": self.fp_cost,
            "fn_cost": self.fn_cost,
            "fn_to_fp_cost_ratio": self.fn_to_fp_cost_ratio,
            "by_clause_type": self.by_clause_type,
            "by_mismatch_type": self.by_mismatch_type,
        }
