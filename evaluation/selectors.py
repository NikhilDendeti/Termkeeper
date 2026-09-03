"""Read-path selector functions for the `evaluation` app.

Every non-trivial read - including reading the committed manifest/fixture
JSON assets under `evaluation/fixtures/` - goes through a function here per
project convention. `score_risk_severity`, `score_mismatch_flags`, and
`compute_cost_report` are pure computations with no side effects (design.md
- Decisions: "pure reads with no side effects, so they live in
selectors.py"); only `run_eval`'s final `EvalRun` persistence is a write and
lives in `services.py`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from evaluation.dataset_types import (
    CostReport,
    HeldoutManifest,
    MismatchFlagScores,
    RiskSeverityScores,
)
from evaluation.models import EvalLabel, EvalLabelType
from razorpay_integration.models import MismatchFlag, MismatchType
from risk_scoring import selectors as risk_scoring_selectors
from risk_scoring.models import SeverityChoices

# Module-level so tests can monkeypatch it to a tmp_path, keeping automated
# tests from ever reading/writing the real committed fixtures directory.
_FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"

# A predicted RiskAssessment.severity is a 4-band categorical
# (low/medium/high/critical/needs_human_review); a label's ground-truth
# `severity` is an integer on a 1-5 scale. This mapping is this harness's
# own, explicitly-stated bridge between the two scales, used only for
# `severity_calibration_score` - see
# specs/evaluation/scoring-harness/spec.md (Requirement: Severity
# calibration reported as a distinct metric).
SEVERITY_TO_FIVE_POINT_SCALE: dict[str, int] = {
    SeverityChoices.LOW.value: 1,
    SeverityChoices.MEDIUM.value: 3,
    SeverityChoices.HIGH.value: 4,
    SeverityChoices.CRITICAL.value: 5,
}

# A stated, named assumption about how much reviewer cost a missed mismatch
# of each type represents, relative to one dismissed false-positive flag -
# see specs/evaluation/scoring-harness/spec.md (Requirement:
# False-positive and false-negative cost report). Not a measured constant;
# see design.md - Risks ("Reviewer-minutes-per-dismissed-flag is a stated
# assumption, not a measured constant").
MISMATCH_TYPE_SEVERITY_WEIGHT: dict[str, float] = {
    MismatchType.CADENCE_MISMATCH.value: 2.0,
    MismatchType.AMOUNT_MISMATCH.value: 3.0,
    MismatchType.MISSING_PLATFORM_EVIDENCE.value: 1.5,
    MismatchType.TRIGGER_CONDITION_UNVERIFIABLE.value: 1.0,
}


# ---------------------------------------------------------------------------
# Held-out manifest (spec: evaluation/scoring-harness)
# ---------------------------------------------------------------------------


def compute_manifest_hash(heldout_engagement_ids: list[str]) -> str:
    """The manifest's own hash mechanism: sha256 over the sorted, newline-joined ids.

    See design.md - Decisions ("Manifest hash mechanism (concrete)"):
    `manifest_sha256 = hashlib.sha256(
    "\\n".join(sorted(heldout_engagement_ids)).encode("utf-8")).hexdigest()`.
    """
    return hashlib.sha256(
        "\n".join(sorted(heldout_engagement_ids)).encode("utf-8")
    ).hexdigest()


def get_heldout_manifest(*, dataset_version: str) -> HeldoutManifest:
    """Read the committed held-out manifest for `dataset_version`.

    Does not itself compare the recorded hash against a freshly computed
    one - `run_eval` does that comparison, keeping the abort-on-mismatch
    decision a service-layer (side-effect-relevant) one. See design.md -
    Decisions.

    Raises:
        FileNotFoundError: if no manifest is committed for `dataset_version`.
    """
    path = _FIXTURES_ROOT / "eval" / dataset_version / "heldout_manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return HeldoutManifest(
        dataset_version=data["dataset_version"],
        heldout_engagement_ids=list(data["heldout_engagement_ids"]),
        recorded_hash=data["manifest_sha256"],
    )


# ---------------------------------------------------------------------------
# Razorpay fixture matrix (spec: evaluation/razorpay-fixtures)
# ---------------------------------------------------------------------------


def get_razorpay_fixture_scenarios(*, fixture_version: str) -> list[dict[str, Any]]:
    """Read the committed Razorpay test-mode fixture matrix for `fixture_version`.

    Raises:
        FileNotFoundError: if no matrix is committed for `fixture_version`.
    """
    path = _FIXTURES_ROOT / "razorpay_scenarios" / f"{fixture_version}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    scenarios: list[dict[str, Any]] = data["scenarios"]
    return scenarios


# ---------------------------------------------------------------------------
# Risk-severity scoring (spec: evaluation/scoring-harness)
# ---------------------------------------------------------------------------


def score_risk_severity(*, dataset_version: str) -> RiskSeverityScores:
    """Score `RiskAssessment.severity` against held-out `risk_severity` labels.

    Scoped to the manifest's committed `heldout_engagement_ids` (the main
    synthetic dataset's held-out split). A label whose ground truth is
    `needs_human_review=True` is excluded from the binary precision/recall/
    F1/calibration figures and instead contributes only to
    `human_review_recall` - see
    specs/evaluation/scoring-harness/spec.md (Requirement: needs_human_review
    scored as a separate recall metric).
    """
    manifest = get_heldout_manifest(dataset_version=dataset_version)
    labels = EvalLabel.objects.filter(
        label_type=EvalLabelType.RISK_SEVERITY,
        clause__isnull=False,
        contract__engagement_id__in=manifest.heldout_engagement_ids,
    ).select_related("clause")

    true_positives = false_positives = true_negatives = false_negatives = 0
    calibration_scores: list[float] = []
    human_review_true_positives = 0
    human_review_total = 0
    scored_clause_count = 0

    for label in labels:
        ground_truth = label.ground_truth_value
        risky = bool(ground_truth.get("risky"))
        needs_human_review = bool(ground_truth.get("needs_human_review"))

        # `clause__isnull=False` above guarantees this at runtime; narrowed
        # explicitly here so the type checker knows it too.
        assert label.clause is not None
        assessment = risk_scoring_selectors.get_risk_assessment_for_clause(clause=label.clause)
        predicted_severity = (
            assessment.severity if assessment is not None else SeverityChoices.LOW.value
        )

        if needs_human_review:
            human_review_total += 1
            if predicted_severity == SeverityChoices.NEEDS_HUMAN_REVIEW.value:
                human_review_true_positives += 1
            continue

        scored_clause_count += 1
        predicted_risky = predicted_severity != SeverityChoices.LOW.value
        if risky and predicted_risky:
            true_positives += 1
        elif (not risky) and predicted_risky:
            false_positives += 1
        elif risky and not predicted_risky:
            false_negatives += 1
        else:
            true_negatives += 1

        labeled_scale = int(ground_truth.get("severity", 1))
        predicted_scale = SEVERITY_TO_FIVE_POINT_SCALE.get(predicted_severity, 1)
        diff = abs(labeled_scale - predicted_scale)
        if diff == 0:
            calibration_scores.append(1.0)
        elif diff == 1:
            calibration_scores.append(0.5)
        else:
            calibration_scores.append(0.0)

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives)
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives)
        else 0.0
    )
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    human_review_recall = (
        human_review_true_positives / human_review_total if human_review_total else 0.0
    )
    severity_calibration_score = (
        sum(calibration_scores) / len(calibration_scores) if calibration_scores else 0.0
    )

    return RiskSeverityScores(
        precision=precision,
        recall=recall,
        f1=f1,
        human_review_recall=human_review_recall,
        severity_calibration_score=severity_calibration_score,
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
        scored_clause_count=scored_clause_count,
        human_review_clause_count=human_review_total,
    )


# ---------------------------------------------------------------------------
# Mismatch-flag scoring (spec: evaluation/scoring-harness)
# ---------------------------------------------------------------------------


def _fixture_engagement_prefix(*, dataset_version: str) -> str:
    return f"synthetic-{dataset_version}-fixture-"


def _mismatch_present_labels_for_dataset(*, dataset_version: str) -> list[EvalLabel]:
    """Held-out `mismatch_present` labels for `dataset_version`.

    Scoped to the fixture-matrix-sourced contracts for this `dataset_version`
    (namespaced `synthetic-{dataset_version}-fixture-*` by
    `evaluation.services.load_razorpay_fixture_scenarios`) rather than the
    main dataset's `heldout_manifest.json` - fixture-matrix scenarios exist
    purely to be scored and are therefore entirely held out by construction,
    independent of the main synthetic dataset's own held-out split. See
    evaluation/services.py::load_razorpay_fixture_scenarios's docstring.
    """
    prefix = _fixture_engagement_prefix(dataset_version=dataset_version)
    return list(
        EvalLabel.objects.filter(
            label_type=EvalLabelType.MISMATCH_PRESENT,
            clause__isnull=False,
            contract__engagement_id__startswith=prefix,
        ).select_related("clause")
    )


def score_mismatch_flags(*, dataset_version: str) -> MismatchFlagScores:
    """Score `MismatchFlag` correctness against held-out `mismatch_present` labels.

    Matches a predicted flag to a ground-truth label by both clause id and
    `mismatch_type` together (set intersection over `(clause_id,
    mismatch_type)` pairs) - a flag with the right clause id but a different
    `mismatch_type` never counts as a true positive. See
    specs/evaluation/scoring-harness/spec.md (Requirement: MismatchFlag
    precision and recall).
    """
    labels = _mismatch_present_labels_for_dataset(dataset_version=dataset_version)
    # `clause__isnull=False` in `_mismatch_present_labels_for_dataset` guarantees
    # `label.clause_id is not None` at runtime; the `is not None` filters below
    # narrow the type for the checker too.
    clause_ids = [label.clause_id for label in labels if label.clause_id is not None]

    expected_pairs: set[tuple[uuid.UUID, str]] = {
        (label.clause_id, label.ground_truth_value["mismatch_type"])
        for label in labels
        if label.clause_id is not None and label.ground_truth_value.get("mismatch_type")
    }

    predicted_pairs: set[tuple[uuid.UUID, str]] = {
        (flag.extracted_term.clause_id, flag.mismatch_type)
        for flag in MismatchFlag.objects.filter(
            extracted_term__clause_id__in=clause_ids
        ).select_related("extracted_term")
    }

    true_positives = len(predicted_pairs & expected_pairs)
    false_positives = len(predicted_pairs - expected_pairs)
    false_negatives = len(expected_pairs - predicted_pairs)

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives)
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives)
        else 0.0
    )

    return MismatchFlagScores(
        precision=precision,
        recall=recall,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


# ---------------------------------------------------------------------------
# Cost report (spec: evaluation/scoring-harness)
# ---------------------------------------------------------------------------


def _bump_cost_bucket(
    bucket: dict[str, dict[str, float]],
    key: str,
    *,
    false_positive_delta: int = 0,
    false_negative_delta: int = 0,
    false_positive_cost_delta: float = 0.0,
    false_negative_cost_delta: float = 0.0,
) -> None:
    entry = bucket.setdefault(
        key, {"fp_count": 0, "fn_count": 0, "fp_cost": 0.0, "fn_cost": 0.0}
    )
    entry["fp_count"] += false_positive_delta
    entry["fn_count"] += false_negative_delta
    entry["fp_cost"] += false_positive_cost_delta
    entry["fn_cost"] += false_negative_cost_delta


def compute_cost_report(*, dataset_version: str, minutes_per_dismissed_flag: float) -> CostReport:
    """FP/FN cost, broken down by `clause_type` and by `mismatch_type`, never blended.

    `FP_cost = minutes_per_dismissed_flag * false_positive_count`. `FN_cost`
    is a severity-weighted sum over missed clauses
    (`MISMATCH_TYPE_SEVERITY_WEIGHT[mismatch_type] * minutes_per_dismissed_flag`
    per missed flag), reported in the same reviewer-minutes unit as FP_cost
    so `fn_to_fp_cost_ratio` is meaningful. See
    specs/evaluation/scoring-harness/spec.md (Requirement: False-positive and
    false-negative cost report).
    """
    labels = _mismatch_present_labels_for_dataset(dataset_version=dataset_version)
    # `clause__isnull=False` in `_mismatch_present_labels_for_dataset` guarantees
    # `label.clause_id is not None`/`label.clause is not None` at runtime; the
    # `is not None` filters below narrow the type for the checker too.
    clause_ids = [label.clause_id for label in labels if label.clause_id is not None]

    expected_by_clause: dict[uuid.UUID, str | None] = {
        label.clause_id: label.ground_truth_value.get("mismatch_type")
        for label in labels
        if label.clause_id is not None
    }
    clause_type_by_clause: dict[uuid.UUID, str] = {
        label.clause_id: (label.clause.clause_type or "unknown")
        for label in labels
        if label.clause_id is not None and label.clause is not None
    }

    expected_pairs: set[tuple[uuid.UUID, str]] = {
        (clause_id, mismatch_type)
        for clause_id, mismatch_type in expected_by_clause.items()
        if mismatch_type
    }
    predicted_pairs: set[tuple[uuid.UUID, str]] = {
        (flag.extracted_term.clause_id, flag.mismatch_type)
        for flag in MismatchFlag.objects.filter(
            extracted_term__clause_id__in=clause_ids
        ).select_related("extracted_term")
    }

    false_positive_pairs = predicted_pairs - expected_pairs
    false_negative_pairs = expected_pairs - predicted_pairs

    fp_count = len(false_positive_pairs)
    fn_count = len(false_negative_pairs)
    fp_cost = minutes_per_dismissed_flag * fp_count
    fn_cost = sum(
        MISMATCH_TYPE_SEVERITY_WEIGHT.get(mismatch_type, 1.0) * minutes_per_dismissed_flag
        for _clause_id, mismatch_type in false_negative_pairs
    )
    ratio = (fn_cost / fp_cost) if fp_cost else None

    by_clause_type: dict[str, dict[str, float]] = {}
    by_mismatch_type: dict[str, dict[str, float]] = {}

    for clause_id, mismatch_type in false_positive_pairs:
        clause_type = clause_type_by_clause.get(clause_id, "unknown")
        _bump_cost_bucket(
            by_clause_type, clause_type,
            false_positive_delta=1, false_positive_cost_delta=minutes_per_dismissed_flag,
        )
        _bump_cost_bucket(
            by_mismatch_type, mismatch_type,
            false_positive_delta=1, false_positive_cost_delta=minutes_per_dismissed_flag,
        )

    for clause_id, mismatch_type in false_negative_pairs:
        clause_type = clause_type_by_clause.get(clause_id, "unknown")
        cost = MISMATCH_TYPE_SEVERITY_WEIGHT.get(mismatch_type, 1.0) * minutes_per_dismissed_flag
        _bump_cost_bucket(
            by_clause_type, clause_type, false_negative_delta=1, false_negative_cost_delta=cost
        )
        _bump_cost_bucket(
            by_mismatch_type, mismatch_type, false_negative_delta=1, false_negative_cost_delta=cost
        )

    return CostReport(
        minutes_per_dismissed_flag=minutes_per_dismissed_flag,
        fp_count=fp_count,
        fn_count=fn_count,
        fp_cost=fp_cost,
        fn_cost=fn_cost,
        fn_to_fp_cost_ratio=ratio,
        by_clause_type=by_clause_type,
        by_mismatch_type=by_mismatch_type,
    )
