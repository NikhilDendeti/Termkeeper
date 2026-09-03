## Purpose

Scores the pipeline's persisted `RiskAssessment` and `MismatchFlag` output against held-out human labels, behind a manifest-hash-enforced split, and reports precision/recall/calibration/cost figures as distinct metrics rather than one blended score.

## ADDED Requirements

### Requirement: Contract-level held-out split
The system SHALL partition the labeled dataset into a held-out set and a non-held-out set at the contract level only. No two clauses belonging to the same contract SHALL be split across the held-out and non-held-out sets.

#### Scenario: No clause-level leakage
- **WHEN** the held-out split is constructed for a `dataset_version`
- **THEN** every clause of a given contract is assigned to the same set as every other clause of that same contract — none of a held-out contract's clauses appear in the non-held-out set or vice versa

### Requirement: Manifest hash enforcement before scoring
The system SHALL refuse to produce scoring results when the hash computed from the current held-out split does not match the hash recorded in the committed manifest for that `dataset_version`, and SHALL abort before persisting any `EvalRun` record when this check fails.

#### Scenario: Mismatched manifest blocks the run
- **WHEN** an eval run is invoked and the live-computed held-out split hash differs from the committed manifest's recorded hash
- **THEN** the run aborts before scoring, no `EvalRun` record is persisted, and no partial precision/recall figures are produced

#### Scenario: Matching manifest proceeds
- **WHEN** the live-computed held-out split hash matches the committed manifest's recorded hash for that `dataset_version`
- **THEN** the eval run proceeds to scoring and produces an `EvalRun` record

### Requirement: Binary risk-severity precision, recall, and F1
The system SHALL compute precision, recall, and F1 for `risk_severity` by comparing, for each held-out clause not labeled `needs_human_review`, whether `RiskAssessment.severity != low` matches the label's `risky` boolean.

#### Scenario: Binary comparison drives the metric
- **WHEN** `risk_severity` is scored for the held-out set
- **THEN** each scored clause contributes a true positive, false positive, true negative, or false negative determined solely by comparing `RiskAssessment.severity != low` against the label's `risky` value

### Requirement: needs_human_review scored as a separate recall metric
Clauses labeled `needs_human_review` in ground truth SHALL be excluded from the `risk_severity` precision/recall/F1 computation and SHALL instead contribute to a distinct `human_review_recall` metric measuring whether the pipeline also marked that clause `needs_human_review`.

#### Scenario: Ambiguous clauses excluded from the binary metric
- **WHEN** a held-out clause is labeled `needs_human_review`
- **THEN** it does not contribute to the `risk_severity` precision/recall/F1 figures, and instead contributes to `human_review_recall` based on whether the pipeline's own `needs_human_review` state agrees with the label

### Requirement: Severity calibration reported as a distinct metric
The system SHALL compute a `severity_calibration_score` per scored clause (1.0 for an exact match between predicted and labeled severity on the 1-5 scale, 0.5 for a difference of exactly one point, 0.0 for any larger difference), and SHALL report the aggregate calibration score as its own `EvalRun` field, never combined into the `risk_severity` F1 value.

#### Scenario: Partial credit for off-by-one severity
- **WHEN** a clause's predicted severity differs from its labeled severity by exactly one point
- **THEN** its calibration score is 0.5

#### Scenario: Calibration never blended into F1
- **WHEN** an `EvalRun`'s metrics are persisted
- **THEN** `severity_calibration_score` is stored as a separate field from the `risk_severity` F1 value, and no computation combines the two into a single blended figure

### Requirement: MismatchFlag precision and recall
The system SHALL compute a precision/recall pair for `MismatchFlag` correctness that is separate from the `risk_severity` metrics, matching a predicted flag to a ground-truth label by both clause id and `mismatch_type`.

#### Scenario: Match requires both clause id and mismatch_type
- **WHEN** scoring `MismatchFlag` correctness for a held-out clause
- **THEN** a predicted flag counts as a true positive only when a ground-truth label with `label_type=mismatch_present` exists for that same clause id and the same `mismatch_type`; a flag matching clause id alone with a different `mismatch_type` does not count as a true positive

### Requirement: False-positive and false-negative cost report
The system SHALL compute `FP_cost` as a stated reviewer-minutes-per-dismissed-flag assumption multiplied by the false-positive count, and `FN_cost` as a severity-weighted sum over missed (false-negative) clauses, and SHALL report the raw FP/FN counts, both cost figures, and the `FN_cost`/`FP_cost` ratio broken down by `clause_type` and by `mismatch_type`, without collapsing them into one combined number.

#### Scenario: Costs broken down, never blended
- **WHEN** an `EvalRun`'s cost report is generated
- **THEN** `FP_cost` and `FN_cost` are each reported broken down by `clause_type` and separately by `mismatch_type`, the `FN_cost`/`FP_cost` ratio is reported alongside them, and no single blended cost figure is produced in place of these breakdowns
