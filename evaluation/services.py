"""Write-path service functions for the `evaluation` app.

Every write (`Contract`/`Clause` for synthetic data, `EvalLabel`, `EvalRun`)
that this app is responsible for goes through a function here, per project
convention. `evaluation` is a pure consumer of `contracts`, `pipeline`,
`razorpay_integration`, and `risk_scoring` - none of those apps import from
`evaluation`, so (unlike `pipeline.services`' stage-4/stage-5 hooks) the
imports below are all module-level; there is no circular-import hazard to
work around. See design.md (add-evaluation-harness) - Decisions.

Deviations from design.md's abbreviated function signatures are called out
inline where they occur (`generate_synthetic_contract` needs `dataset_version`
and `sequence_number` to build `engagement_id`; `run_eval` needs
`fixture_version` to satisfy the razorpay-fixtures spec's "EvalRun records
the fixture version used" requirement, which design.md's own EvalRun field
list omits).
"""

from __future__ import annotations

import random
import subprocess
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction

from contracts import selectors as contracts_selectors
from contracts import services as contracts_services
from contracts.models import Clause, ClauseType, Contract
from core import llm_client
from evaluation import selectors as evaluation_selectors
from evaluation.dataset_types import (
    ClauseGroundTruth,
    ClauseSeverityProfile,
    Domain,
    EngagementType,
    PhrasingStyle,
    SyntheticContractParams,
)
from evaluation.models import EvalLabel, EvalLabelType, EvalRun
from pipeline.models import AuditLogEntry, ExtractedTerm
from razorpay_integration import services as razorpay_integration_services

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SyntheticGenerationError(RuntimeError):
    """Raised when synthetic contract generation produces an unusable shape.

    E.g. the phrasing call returns a different number of paragraphs than
    ground-truth clause specs, or labeling can't line up 1:1 with the
    contract's persisted Clause rows.
    """


class ManifestIntegrityError(RuntimeError):
    """Raised when the held-out manifest fails its integrity check.

    Covers both failure modes described in
    specs/evaluation/scoring-harness/spec.md (Requirement: Manifest hash
    enforcement before scoring): a recomputed hash that doesn't match the
    manifest's recorded hash, and a listed engagement_id with no matching
    Contract row. `run_eval` raises this before persisting any EvalRun row.
    """


# ---------------------------------------------------------------------------
# Ground-truth-first clause generation (spec: evaluation/synthetic-dataset)
# ---------------------------------------------------------------------------

# Every synthetic contract carries exactly these five clause "slots", in
# this order - a fixed, deterministic shape chosen so `label_synthetic_contract`
# can line labels up with segmented Clause rows by position (sequence_index)
# without ever having to parse clause_text. Three of the five
# (payment_schedule, penalty_late_fee, auto_renewal) are the payment-bearing
# types pipeline stage 3 extracts from; termination and dispute_resolution
# add clause-type/criticality-weight variety for risk-scoring (stage 5).
_CLAUSE_SLOTS: tuple[str, ...] = (
    ClauseType.PAYMENT_SCHEDULE.value,
    ClauseType.PENALTY_LATE_FEE.value,
    ClauseType.TERMINATION.value,
    ClauseType.AUTO_RENEWAL.value,
    ClauseType.DISPUTE_RESOLUTION.value,
)

# A stable (process-independent) integer salt per clause type, used to seed
# each clause's own `random.Random` instance deterministically. Deliberately
# NOT `hash(clause_type)`: Python's string hashing is randomized per-process
# by default (PYTHONHASHSEED), which would break the "same seed -> identical
# ground truth" guarantee task 2.1 requires across separate runs.
_CLAUSE_TYPE_SALT: dict[str, int] = {
    ClauseType.PAYMENT_SCHEDULE.value: 11,
    ClauseType.PENALTY_LATE_FEE.value: 22,
    ClauseType.TERMINATION.value: 33,
    ClauseType.AUTO_RENEWAL.value: 44,
    ClauseType.DISPUTE_RESOLUTION.value: 55,
}

# Each clause independently rolls whether it follows the contract's dominant
# `clause_severity_profile` or drifts to a different one - see
# specs/evaluation/synthetic-dataset/spec.md (Requirement: Five-axis dataset
# coverage - Scenario: Severity varies within one contract).
_PROFILE_DRIFT_CHANCE = 0.35

_OTHER_PROFILES: dict[str, tuple[str, str]] = {
    ClauseSeverityProfile.FAIR.value: (
        ClauseSeverityProfile.MILDLY_ONE_SIDED.value,
        ClauseSeverityProfile.DELIBERATELY_EXPLOITATIVE.value,
    ),
    ClauseSeverityProfile.MILDLY_ONE_SIDED.value: (
        ClauseSeverityProfile.FAIR.value,
        ClauseSeverityProfile.DELIBERATELY_EXPLOITATIVE.value,
    ),
    ClauseSeverityProfile.DELIBERATELY_EXPLOITATIVE.value: (
        ClauseSeverityProfile.FAIR.value,
        ClauseSeverityProfile.MILDLY_ONE_SIDED.value,
    ),
}

_SEVERITY_RANGE_BY_PROFILE: dict[str, tuple[int, int]] = {
    ClauseSeverityProfile.FAIR.value: (1, 2),
    ClauseSeverityProfile.MILDLY_ONE_SIDED.value: (2, 4),
    ClauseSeverityProfile.DELIBERATELY_EXPLOITATIVE.value: (4, 5),
}

_PAYMENT_CADENCE_DAYS_BASE: dict[str, float] = {
    ClauseSeverityProfile.FAIR.value: 30.0,
    ClauseSeverityProfile.MILDLY_ONE_SIDED.value: 45.0,
    ClauseSeverityProfile.DELIBERATELY_EXPLOITATIVE.value: 90.0,
}
_PENALTY_PCT_BASE: dict[str, float] = {
    ClauseSeverityProfile.FAIR.value: 1.5,
    ClauseSeverityProfile.MILDLY_ONE_SIDED.value: 5.0,
    ClauseSeverityProfile.DELIBERATELY_EXPLOITATIVE.value: 15.0,
}
# Lower notice = more one-sided (the vendor gets less warning).
_TERMINATION_NOTICE_DAYS_BASE: dict[str, float] = {
    ClauseSeverityProfile.FAIR.value: 30.0,
    ClauseSeverityProfile.MILDLY_ONE_SIDED.value: 14.0,
    ClauseSeverityProfile.DELIBERATELY_EXPLOITATIVE.value: 2.0,
}
_AUTO_RENEWAL_OPT_OUT_NOTICE_DAYS_BASE: dict[str, float] = {
    ClauseSeverityProfile.FAIR.value: 30.0,
    ClauseSeverityProfile.MILDLY_ONE_SIDED.value: 10.0,
    ClauseSeverityProfile.DELIBERATELY_EXPLOITATIVE.value: 1.0,
}
_AMOUNT_BASE_BY_ENGAGEMENT: dict[str, float] = {
    EngagementType.FIXED_FEE.value: 5000.0,
    EngagementType.MILESTONE.value: 8000.0,
    EngagementType.RETAINER.value: 3000.0,
}
_AMOUNT_MULTIPLIER_BY_DOMAIN: dict[str, float] = {
    Domain.DESIGN.value: 1.0,
    Domain.DEV.value: 1.3,
    Domain.CONTENT.value: 0.7,
    Domain.CONSULTING.value: 1.5,
}

_MECHANISM_BY_CLAUSE_TYPE: dict[str, str] = {
    ClauseType.PAYMENT_SCHEDULE.value: "a delayed or extended payout cadence",
    ClauseType.PENALTY_LATE_FEE.value: "a one-sided late-payment penalty",
    ClauseType.TERMINATION.value: "unilateral or asymmetric termination rights",
    ClauseType.AUTO_RENEWAL.value: "a silent auto-renewal lock-in with little opt-out notice",
    ClauseType.DISPUTE_RESOLUTION.value: "a forum or cost burden imposed on the vendor",
}

_NEEDS_HUMAN_REVIEW_CHANCE = 0.15


def _clause_seed(*, seed: int, index: int, clause_type: str) -> int:
    """A deterministic, process-independent per-clause seed derived from `seed`."""
    return seed * 1000 + index * 100 + _CLAUSE_TYPE_SALT[clause_type]


def _jitter(rng: random.Random, base: float, *, spread: float = 0.1) -> float:
    return base * (1 + rng.uniform(-spread, spread))


def _rationale(*, clause_type: str, severity_profile: str) -> str:
    mechanism = _MECHANISM_BY_CLAUSE_TYPE[clause_type]
    clause_label = clause_type.replace("_", " ")
    if severity_profile == ClauseSeverityProfile.FAIR.value:
        return (
            f"The {clause_label} clause is balanced and does not rely on {mechanism} "
            "to disadvantage the vendor."
        )
    if severity_profile == ClauseSeverityProfile.MILDLY_ONE_SIDED.value:
        return (
            f"The {clause_label} clause leans on {mechanism}, moderately disadvantaging "
            "the vendor relative to the counterparty."
        )
    return (
        f"The {clause_label} clause imposes {mechanism}, severely disadvantaging the "
        "vendor relative to the counterparty."
    )


def generate_clause_ground_truth(*, params: SyntheticContractParams) -> list[ClauseGroundTruth]:
    """Pure, seeded generation of every synthetic clause's ground truth.

    Deterministic in `params` alone (in particular `params.seed`) - two
    calls with identical `params` return identical results (task 2.1's
    guarantee). Each clause's `severity_profile` is rolled independently of
    the contract's dominant `clause_severity_profile` axis value, so a
    predominantly-fair contract can still contain a deliberately-exploitative
    clause (task 2.3). See
    specs/evaluation/synthetic-dataset/spec.md (Requirement: Five-axis
    dataset coverage - Scenario: Severity varies within one contract;
    Requirement: Ground truth generated before prose).
    """
    ground_truths: list[ClauseGroundTruth] = []
    for index, clause_type in enumerate(_CLAUSE_SLOTS):
        rng = random.Random(_clause_seed(seed=params.seed, index=index, clause_type=clause_type))

        if rng.random() < _PROFILE_DRIFT_CHANCE:
            severity_profile = rng.choice(_OTHER_PROFILES[params.clause_severity_profile])
        else:
            severity_profile = params.clause_severity_profile

        severity_lo, severity_hi = _SEVERITY_RANGE_BY_PROFILE[severity_profile]
        severity = rng.randint(severity_lo, severity_hi)
        risky = severity_profile != ClauseSeverityProfile.FAIR.value
        needs_human_review = rng.random() < _NEEDS_HUMAN_REVIEW_CHANCE

        amount: float | None = None
        cadence_days: float | None = None
        notice_period_days: int | None = None
        penalty_pct: float | None = None

        if clause_type == ClauseType.PAYMENT_SCHEDULE.value:
            cadence_days = round(_jitter(rng, _PAYMENT_CADENCE_DAYS_BASE[severity_profile]))
            base_amount = _AMOUNT_BASE_BY_ENGAGEMENT[params.engagement_type]
            base_amount *= _AMOUNT_MULTIPLIER_BY_DOMAIN[params.domain]
            amount = round(_jitter(rng, base_amount), 2)
        elif clause_type == ClauseType.PENALTY_LATE_FEE.value:
            penalty_pct = round(_jitter(rng, _PENALTY_PCT_BASE[severity_profile]), 2)
        elif clause_type == ClauseType.TERMINATION.value:
            notice_period_days = max(
                1, round(_jitter(rng, _TERMINATION_NOTICE_DAYS_BASE[severity_profile]))
            )
        elif clause_type == ClauseType.AUTO_RENEWAL.value:
            cadence_days = round(_jitter(rng, 365.0, spread=0.02))
            notice_period_days = max(
                1,
                round(_jitter(rng, _AUTO_RENEWAL_OPT_OUT_NOTICE_DAYS_BASE[severity_profile])),
            )
        # dispute_resolution carries no numeric ground truth - risky/severity
        # come from severity_profile alone.

        ground_truths.append(
            ClauseGroundTruth(
                clause_type=clause_type,
                severity_profile=severity_profile,
                amount=amount,
                cadence_days=cadence_days,
                notice_period_days=notice_period_days,
                penalty_pct=penalty_pct,
                risky=risky,
                severity=severity,
                rationale=_rationale(clause_type=clause_type, severity_profile=severity_profile),
                needs_human_review=needs_human_review,
            )
        )
    return ground_truths


def compute_overall_risk_tier(*, clause_severities: list[int]) -> str:
    """Contract-level `overall_risk_tier` with the floor rule applied.

    See specs/evaluation/synthetic-dataset/spec.md (Requirement: Per-contract
    risk tier with a floor rule): forced to `critical` whenever 2+ clauses
    are severity>=4, regardless of whether any single clause reaches 5.
    """
    if not clause_severities:
        return "low"
    high_severity_count = sum(1 for severity in clause_severities if severity >= 4)
    if high_severity_count >= 2:
        return "critical"
    max_severity = max(clause_severities)
    if max_severity >= 5:
        return "critical"
    if max_severity >= 4:
        return "high"
    if max_severity >= 3:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Prose phrasing (one model call per contract)
# ---------------------------------------------------------------------------

_PHRASING_PROMPT_VERSION = "synthetic-contract-phrasing-v1"

_PHRASING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clauses"],
    "additionalProperties": False,
}

_PHRASING_STYLE_INSTRUCTIONS: dict[str, str] = {
    PhrasingStyle.PLAIN.value: "Use plain, direct business English.",
    PhrasingStyle.LEGALESE.value: (
        "Use dense, formal legal drafting conventions (defined terms, "
        '"WHEREAS", "the Party of the first part" style phrasing).'
    ),
    PhrasingStyle.DELIBERATELY_VAGUE.value: (
        "State every numeric value indirectly and qualitatively (e.g. "
        '"on a regular monthly basis" rather than "every 30 days", '
        '"a reasonable notice period" rather than an exact day count) - '
        "never spell out the exact number given below verbatim."
    ),
}


def _build_phrasing_system_prompt() -> str:
    return (
        "You write freelance/vendor contract clauses from a structured "
        "ground-truth specification. You will be given a list of clause "
        "specs, each with a clause_type and its ground-truth numeric "
        "values. Return exactly one prose paragraph per spec, in the same "
        "order, as the `clauses` array. Each paragraph must faithfully "
        "express its spec's ground-truth values (a human reading the "
        "paragraph could recover them), phrased in the requested style. "
        "Do not add clauses, omit clauses, or reorder them."
    )


def _describe_ground_truth(ground_truth: ClauseGroundTruth) -> str:
    parts = [f"clause_type={ground_truth.clause_type}"]
    if ground_truth.amount is not None:
        parts.append(f"amount={ground_truth.amount}")
    if ground_truth.cadence_days is not None:
        parts.append(f"cadence_days={ground_truth.cadence_days}")
    if ground_truth.notice_period_days is not None:
        parts.append(f"notice_period_days={ground_truth.notice_period_days}")
    if ground_truth.penalty_pct is not None:
        parts.append(f"penalty_pct={ground_truth.penalty_pct}")
    return ", ".join(parts)


def _build_phrasing_user_content(
    *, ground_truths: list[ClauseGroundTruth], phrasing_style: str
) -> str:
    style_instruction = _PHRASING_STYLE_INSTRUCTIONS[phrasing_style]
    lines = [f"phrasing_style: {phrasing_style}. {style_instruction}", "", "Clause specs:"]
    for index, ground_truth in enumerate(ground_truths, start=1):
        lines.append(f"{index}. {_describe_ground_truth(ground_truth)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Synthetic contract generation and labeling (spec: evaluation/synthetic-dataset)
# ---------------------------------------------------------------------------


def generate_synthetic_contract(
    *, params: SyntheticContractParams, dataset_version: str, sequence_number: int
) -> Contract:
    """Generate one synthetic Contract: ground truth first, then prose.

    Deviates from design.md's abbreviated `(*, params) -> Contract` signature
    by requiring `dataset_version`/`sequence_number` as well - both are
    needed to build the `engagement_id="synthetic-{dataset_version}-{n}"`
    design.md itself specifies, and `SyntheticContractParams` (task 1.3)
    deliberately carries only the five axis values plus `seed`.

    Ground truth is generated first (pure, seeded -
    `generate_clause_ground_truth`) and handed to the phrasing call as
    input; the returned Contract's `raw_text` is never parsed to recover
    ground truth. Persists Clause rows directly, in ground-truth order, so
    `label_synthetic_contract` can attach labels by position without ever
    reading `clause_text`/`raw_text` - segmentation-by-LLM is deliberately
    not used for synthetic contracts (clause boundaries are already known
    from generation); classification and extraction are still deferred to
    `pipeline.services.run_pipeline(from_stage=2)`, run against the
    contract exactly as it would be for any other contract.

    See specs/evaluation/synthetic-dataset/spec.md (Requirement: Ground
    truth generated before prose).
    """
    ground_truths = generate_clause_ground_truth(params=params)

    result = llm_client.get_structured_completion(
        _build_phrasing_system_prompt(),
        _build_phrasing_user_content(
            ground_truths=ground_truths, phrasing_style=params.phrasing_style
        ),
        _PHRASING_SCHEMA,
        prompt_version=_PHRASING_PROMPT_VERSION,
    )
    paragraphs = [item["text"] for item in result["clauses"]]
    if len(paragraphs) != len(ground_truths):
        raise SyntheticGenerationError(
            f"expected {len(ground_truths)} phrased clause paragraphs, got {len(paragraphs)}"
        )

    clause_texts = [f"{index + 1}. {text}" for index, text in enumerate(paragraphs)]
    raw_text = "\n\n".join(clause_texts)
    engagement_id = f"synthetic-{dataset_version}-{sequence_number:03d}"

    contract = contracts_services.create_contract(
        raw_text=raw_text,
        engagement_id=engagement_id,
        razorpay_reference_type=params.razorpay_reference_type,
        razorpay_reference_id=f"{engagement_id}-{params.razorpay_reference_type}",
    )

    with transaction.atomic():
        for index, clause_text in enumerate(clause_texts):
            Clause.objects.create(contract=contract, sequence_index=index, clause_text=clause_text)

    return contract


def label_synthetic_contract(
    *, contract: Contract, params: SyntheticContractParams
) -> list[EvalLabel]:
    """Write per-clause and per-contract EvalLabel rows for a synthetic Contract.

    Ground truth is recomputed by calling `generate_clause_ground_truth`
    again with the same `params` (pure and seeded, so this reproduces the
    exact values `generate_synthetic_contract` used) - never re-derived from
    `contract.raw_text`/`clause.clause_text`. See
    specs/evaluation/synthetic-dataset/spec.md (Requirement: Per-clause human
    labeling rubric, Requirement: Per-contract risk tier with a floor rule).
    """
    ground_truths = generate_clause_ground_truth(params=params)
    clauses = list(contracts_selectors.list_clauses_for_contract(contract=contract))
    if len(clauses) != len(ground_truths):
        raise SyntheticGenerationError(
            f"contract {contract.id} has {len(clauses)} clauses but "
            f"{len(ground_truths)} ground-truth specs were generated for it"
        )

    labels: list[EvalLabel] = []
    with transaction.atomic():
        for clause, ground_truth in zip(clauses, ground_truths, strict=True):
            labels.append(
                EvalLabel.objects.create(
                    contract=contract,
                    clause=clause,
                    label_type=EvalLabelType.RISK_SEVERITY,
                    ground_truth_value={
                        "clause_type": ground_truth.clause_type,
                        "risky": ground_truth.risky,
                        "severity": ground_truth.severity,
                        "rationale": ground_truth.rationale,
                        "needs_human_review": ground_truth.needs_human_review,
                        "amount": ground_truth.amount,
                        "cadence_days": ground_truth.cadence_days,
                        "notice_period_days": ground_truth.notice_period_days,
                        "penalty_pct": ground_truth.penalty_pct,
                    },
                    annotator="synthetic-rubric-v1",
                )
            )

        overall_risk_tier = compute_overall_risk_tier(
            clause_severities=[ground_truth.severity for ground_truth in ground_truths]
        )
        labels.append(
            EvalLabel.objects.create(
                contract=contract,
                clause=None,
                label_type=EvalLabelType.RISK_SEVERITY,
                ground_truth_value={"overall_risk_tier": overall_risk_tier},
                annotator="synthetic-rubric-v1",
            )
        )
    return labels


# ---------------------------------------------------------------------------
# Full dataset generation (spec: evaluation/synthetic-dataset - Dataset size
# bounds, Five-axis dataset coverage)
# ---------------------------------------------------------------------------

_ENGAGEMENT_TYPES: list[str] = [choice.value for choice in EngagementType]
_DOMAINS: list[str] = [choice.value for choice in Domain]
_SEVERITY_PROFILES: list[str] = [choice.value for choice in ClauseSeverityProfile]
_PHRASING_STYLES: list[str] = [choice.value for choice in PhrasingStyle]
_REFERENCE_TYPES: list[str] = ["payout", "subscription"]

DEFAULT_DATASET_SIZE = 36
_HELDOUT_SPLIT_SEED = 42
_HELDOUT_FRACTION = 0.2


def _synthetic_contract_params_for_index(*, index: int) -> SyntheticContractParams:
    """The exact `SyntheticContractParams` `build_dataset_params` assigns at position `index`.

    Depends only on `index` (never on the total `count` a dataset happened to
    be generated with) - every axis value is `index % len(axis)` and
    `seed=1000 + index`. This means a contract's original generation
    parameters can be recomputed later purely from its `engagement_id`'s
    sequence number, without `SyntheticContractParams` ever needing to be
    persisted anywhere - `export_dataset_snapshot` relies on exactly this to
    reconstruct `params` per contract. See design.md (close-pitch-accuracy-gaps)
    - Decisions.
    """
    return SyntheticContractParams(
        engagement_type=_ENGAGEMENT_TYPES[index % len(_ENGAGEMENT_TYPES)],
        domain=_DOMAINS[index % len(_DOMAINS)],
        clause_severity_profile=_SEVERITY_PROFILES[index % len(_SEVERITY_PROFILES)],
        phrasing_style=_PHRASING_STYLES[index % len(_PHRASING_STYLES)],
        razorpay_reference_type=_REFERENCE_TYPES[index % len(_REFERENCE_TYPES)],
        seed=1000 + index,
    )


def build_dataset_params(
    *, count: int = DEFAULT_DATASET_SIZE
) -> list[SyntheticContractParams]:
    """Build `count` SyntheticContractParams covering every axis value at least once.

    Round-robin-cycles each axis independently (modulo its own length) over
    `count` contracts - since `count` (30-50) exceeds every axis's length
    (at most 4), every axis value is guaranteed to appear at least once. See
    specs/evaluation/synthetic-dataset/spec.md (Requirement: Five-axis
    dataset coverage, Requirement: Dataset size bounds).
    """
    if not (30 <= count <= 50):
        raise ValueError(f"dataset size must be between 30 and 50 inclusive, got {count}")

    return [_synthetic_contract_params_for_index(index=index) for index in range(count)]


def generate_dataset(
    *, dataset_version: str, count: int = DEFAULT_DATASET_SIZE
) -> list[Contract]:
    """Generate and label the full synthetic dataset for `dataset_version`.

    See specs/evaluation/synthetic-dataset/spec.md (Requirement: Dataset
    size bounds, Requirement: Five-axis dataset coverage).
    """
    contracts: list[Contract] = []
    for sequence_number, params in enumerate(build_dataset_params(count=count), start=1):
        contract = generate_synthetic_contract(
            params=params, dataset_version=dataset_version, sequence_number=sequence_number
        )
        label_synthetic_contract(contract=contract, params=params)
        contracts.append(contract)
    return contracts


def _engagement_sequence_number(*, engagement_id: str, prefix: str) -> int | None:
    """The integer sequence number encoded in `engagement_id`, or `None` if it isn't one.

    `engagement_id`s under `prefix` come in two disjoint shapes:
    `synthetic-{dataset_version}-{sequence_number:03d}` (the main dataset,
    `generate_synthetic_contract`) and
    `synthetic-{dataset_version}-fixture-{scenario_id}` (the razorpay
    fixture matrix, `load_razorpay_fixture_scenarios`). Only the former is a
    plain digit suffix, which this uses to tell the two apart without a
    regex.
    """
    suffix = engagement_id[len(prefix) :]
    return int(suffix) if suffix.isdigit() else None


def export_dataset_snapshot(*, dataset_version: str) -> dict[str, Any]:
    """Serialize every generated-and-labeled contract for `dataset_version` to portable JSON.

    Scoped to the main synthetic dataset only - `engagement_id`s matching
    `synthetic-{dataset_version}-{sequence_number}` exactly
    (`generate_synthetic_contract`'s own naming convention). Deliberately
    excludes `synthetic-{dataset_version}-fixture-*` contracts
    (`load_razorpay_fixture_scenarios`'s separately-namespaced contracts,
    which are a different artifact with their own committed fixture matrix
    under `evaluation/fixtures/razorpay_scenarios/`).

    Each contract's original `SyntheticContractParams` is recomputed from its
    sequence position (`_synthetic_contract_params_for_index`) rather than
    read from any stored field - `generate_synthetic_contract` never
    persists `SyntheticContractParams` itself, only the Contract/Clause/
    EvalLabel rows downstream of it - so this recovers the *same* params
    `generate_dataset` used, deterministically, from the `engagement_id`
    alone.

    See specs/evaluation/dataset-snapshot-export/spec.md (Requirement:
    Dataset export is portable and complete).
    """
    prefix = f"synthetic-{dataset_version}-"
    candidate_contracts = Contract.objects.filter(engagement_id__startswith=prefix).order_by(
        "engagement_id"
    )

    contract_entries: list[dict[str, Any]] = []
    for contract in candidate_contracts:
        sequence_number = _engagement_sequence_number(
            engagement_id=contract.engagement_id, prefix=prefix
        )
        if sequence_number is None:
            continue

        params = _synthetic_contract_params_for_index(index=sequence_number - 1)
        labels = EvalLabel.objects.filter(contract=contract).select_related("clause")

        contract_entries.append(
            {
                "engagement_id": contract.engagement_id,
                "raw_text": contract.raw_text,
                "params": {
                    "engagement_type": params.engagement_type,
                    "domain": params.domain,
                    "clause_severity_profile": params.clause_severity_profile,
                    "phrasing_style": params.phrasing_style,
                    "razorpay_reference_type": params.razorpay_reference_type,
                    "seed": params.seed,
                },
                "labels": [
                    {
                        "label_type": label.label_type,
                        "clause_sequence_index": (
                            label.clause.sequence_index if label.clause is not None else None
                        ),
                        "ground_truth_value": label.ground_truth_value,
                        "annotator": label.annotator,
                    }
                    for label in labels
                ],
            }
        )

    return {
        "dataset_version": dataset_version,
        "generated_at_note": (
            "Exported by evaluation.services.export_dataset_snapshot from a live "
            "generated-and-labeled dataset. Per-contract params are recomputed "
            "deterministically from each contract's sequence position "
            "(_synthetic_contract_params_for_index), not read from any stored field - "
            "re-running the exporter against the same rows reproduces this file exactly."
        ),
        "contracts": contract_entries,
    }


def assign_heldout_split(
    *,
    engagement_ids: list[str],
    seed: int = _HELDOUT_SPLIT_SEED,
    heldout_fraction: float = _HELDOUT_FRACTION,
) -> list[str]:
    """Deterministically assign a contract-level held-out subset.

    Operates on `engagement_id`s only (contract granularity) - a clause
    never has its own, independent split assignment, so "no clause-level
    leakage" (specs/evaluation/scoring-harness/spec.md) holds by
    construction: every clause inherits its contract's membership. See task
    3.1.
    """
    ordered = sorted(engagement_ids)
    shuffled = ordered[:]
    random.Random(seed).shuffle(shuffled)
    heldout_count = max(1, round(len(shuffled) * heldout_fraction)) if shuffled else 0
    return sorted(shuffled[:heldout_count])


# ---------------------------------------------------------------------------
# Razorpay fixture-matrix loading (spec: evaluation/razorpay-fixtures)
# ---------------------------------------------------------------------------

FIXTURE_ENGAGEMENT_PREFIX_TEMPLATE = "synthetic-{dataset_version}-fixture-"


class _FixtureRazorpayConnector:
    """A canned-payload stand-in for `razorpay_integration.client.RazorpayConnector`.

    Never dispatches a network call of any kind - every method returns a
    slice of the fixture scenario's own committed payload. Constructed with
    the project's (only) Razorpay credential pair, which is already
    test-mode-scoped (see config/settings/base.py -
    "RazorpayX test-mode credentials (read-scope)") - stored for
    documentation/testability, never used to actually dispatch anything. See
    specs/evaluation/razorpay-fixtures/spec.md (Requirement: Fixtures are
    test-mode only).
    """

    def __init__(self, *, payload: dict[str, Any], key_id: str, key_secret: str) -> None:
        self._payload = payload
        self.key_id = key_id
        self.key_secret = key_secret

    def fetch_payouts(self, *, fund_account_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._payload.get("payouts", {"items": []})
        return result

    def fetch_subscription(self, *, subscription_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._payload.get("subscription", {})
        return result

    def fetch_token(self, *, customer_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._payload.get("tokens", {"items": []})
        return result


def load_razorpay_fixture_scenarios(
    *, fixture_version: str, dataset_version: str
) -> list[EvalLabel]:
    """Materialize every fixture-matrix scenario and run stage 4 against it.

    For each committed scenario: persists a dedicated Contract/Clause/
    ExtractedTerm triple from the scenario's own ground truth (never derived
    from generated prose - there is none), swaps
    `razorpay_integration.services.RazorpayConnector` for a
    `_FixtureRazorpayConnector` bound to that scenario's committed payload
    for the duration of the call (the only way to feed `detect_mismatches`
    committed test-mode data without editing razorpay_integration itself -
    see design.md's note that `evaluation` never modifies a prior phase's
    files), calls the real `razorpay_integration.services.detect_mismatches`
    unmodified, and records the scenario's expected verdict as an
    `EvalLabel(label_type=mismatch_present)`.

    Every fixture-scenario Contract's `engagement_id` is namespaced
    `synthetic-{dataset_version}-fixture-{scenario_id}` - these contracts
    exist purely to be scored (never as unlabeled "training" examples), so
    `score_mismatch_flags`/`compute_cost_report` treat every contract under
    this prefix as held out by construction, independent of the main
    dataset's committed heldout_manifest.json (which governs the risk_severity
    split over the non-fixture synthetic contracts only).

    See specs/evaluation/razorpay-fixtures/spec.md (all requirements).
    """
    scenarios = evaluation_selectors.get_razorpay_fixture_scenarios(fixture_version=fixture_version)
    prefix = FIXTURE_ENGAGEMENT_PREFIX_TEMPLATE.format(dataset_version=dataset_version)

    labels: list[EvalLabel] = []
    for scenario in scenarios:
        engagement_id = f"{prefix}{scenario['scenario_id']}"
        contract = contracts_services.create_contract(
            raw_text=scenario["clause_text"],
            engagement_id=engagement_id,
            razorpay_reference_type=scenario["razorpay_reference_type"],
            razorpay_reference_id=f"{engagement_id}-ref",
        )
        clause = Clause.objects.create(
            contract=contract,
            sequence_index=0,
            clause_text=scenario["clause_text"],
            clause_type=scenario["clause_type"],
        )
        term_spec = scenario["extracted_term"]
        ExtractedTerm.objects.create(
            clause=clause,
            term_type=term_spec["term_type"],
            value_raw=term_spec["value_raw"],
            value_structured=term_spec["value_structured"],
            extraction_confidence=term_spec["extraction_confidence"],
            needs_human_review=False,
        )

        connector = _FixtureRazorpayConnector(
            payload=scenario["razorpay_payload"],
            key_id=settings.RAZORPAY_KEY_ID,
            key_secret=settings.RAZORPAY_KEY_SECRET,
        )
        # `setattr`/`getattr` (rather than a direct attribute assignment) so
        # this doesn't read as rebinding a class name to a different type -
        # the swap is still exactly the same "patch the module attribute
        # detect_mismatches reads RazorpayConnector from" technique
        # razorpay_integration's own tests use (see
        # razorpay_integration/tests/test_payout_crosscheck.py's
        # `_FakeConnector`), just without importing `unittest.mock` into
        # production code.
        original_connector_cls = razorpay_integration_services.RazorpayConnector
        setattr(  # noqa: B010
            razorpay_integration_services,
            "RazorpayConnector",
            lambda *args, _connector=connector, **kwargs: _connector,
        )
        try:
            razorpay_integration_services.detect_mismatches(contract=contract)
        finally:
            setattr(  # noqa: B010
                razorpay_integration_services, "RazorpayConnector", original_connector_cls
            )

        labels.append(
            EvalLabel.objects.create(
                contract=contract,
                clause=clause,
                label_type=EvalLabelType.MISMATCH_PRESENT,
                ground_truth_value={
                    "mismatch_type": scenario.get("expected_mismatch_type"),
                    "expected_verdict": scenario["expected_verdict"],
                },
                annotator="synthetic-rubric-v1",
            )
        )
    return labels


# ---------------------------------------------------------------------------
# Eval run orchestration (spec: evaluation/scoring-harness)
# ---------------------------------------------------------------------------

_DEFAULT_FIXTURE_VERSION = "v1"
_DEFAULT_MINUTES_PER_DISMISSED_FLAG = 5.0


def _get_pipeline_version() -> str:
    """Best-effort git short SHA of the code under test; "unknown" if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
            timeout=5,
        )
    except Exception:
        return "unknown"
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return "unknown"


def run_eval(
    *,
    dataset_version: str,
    fixture_version: str = _DEFAULT_FIXTURE_VERSION,
    minutes_per_dismissed_flag: float = _DEFAULT_MINUTES_PER_DISMISSED_FLAG,
) -> EvalRun:
    """Score the pipeline's persisted output against held-out labels.

    Deviates from design.md's abbreviated `(*, dataset_version) -> EvalRun`
    signature by accepting `fixture_version` as well, so it can be recorded
    on the persisted `EvalRun` row per
    specs/evaluation/razorpay-fixtures/spec.md ("EvalRun records the fixture
    version used") - a field design.md's own EvalRun field list omits from
    its enumeration but the razorpay-fixtures spec requires.

    Aborts with `ManifestIntegrityError` (no EvalRun row written) if the
    manifest's recorded hash doesn't match a hash freshly recomputed over
    its own listed contract ids, or if any listed engagement_id has no
    matching Contract row. See
    specs/evaluation/scoring-harness/spec.md (Requirement: Manifest hash
    enforcement before scoring).
    """
    manifest = evaluation_selectors.get_heldout_manifest(dataset_version=dataset_version)

    recomputed_hash = evaluation_selectors.compute_manifest_hash(manifest.heldout_engagement_ids)
    if recomputed_hash != manifest.recorded_hash:
        raise ManifestIntegrityError(
            f"heldout manifest for dataset_version={dataset_version!r} is corrupted or was "
            f"hand-edited without recomputing its checksum: recorded_hash="
            f"{manifest.recorded_hash!r}, recomputed_hash={recomputed_hash!r}."
        )

    missing_ids = [
        engagement_id
        for engagement_id in manifest.heldout_engagement_ids
        if not Contract.objects.filter(engagement_id=engagement_id).exists()
    ]
    if missing_ids:
        raise ManifestIntegrityError(
            f"heldout manifest for dataset_version={dataset_version!r} lists engagement_ids "
            f"with no matching Contract row: {missing_ids!r}."
        )

    risk_scores = evaluation_selectors.score_risk_severity(dataset_version=dataset_version)
    mismatch_scores = evaluation_selectors.score_mismatch_flags(dataset_version=dataset_version)
    cost_report = evaluation_selectors.compute_cost_report(
        dataset_version=dataset_version, minutes_per_dismissed_flag=minutes_per_dismissed_flag
    )

    prompt_versions = sorted(
        set(
            AuditLogEntry.objects.filter(
                contract__engagement_id__in=manifest.heldout_engagement_ids
            ).values_list("prompt_version", flat=True)
        )
    )

    return EvalRun.objects.create(
        dataset_version=dataset_version,
        fixture_version=fixture_version,
        precision_recall_f1={
            "risk_severity": risk_scores.as_dict(),
            "mismatch_present": mismatch_scores.as_dict(),
        },
        severity_calibration_score=risk_scores.severity_calibration_score,
        cost_report=cost_report.as_dict(),
        false_positive_cost_note=(
            f"FP_cost assumes {minutes_per_dismissed_flag} reviewer-minutes per dismissed "
            "(false-positive) mismatch flag, multiplied by the false-positive count. FN_cost "
            "is a severity-weighted sum over missed (false-negative) mismatch clauses. Both "
            "are broken down by clause_type and by mismatch_type in cost_report - see "
            "cost_report.by_clause_type / cost_report.by_mismatch_type; no single blended "
            "cost figure is produced in place of that breakdown."
        ),
        pipeline_version=_get_pipeline_version(),
        prompt_version=",".join(prompt_versions),
    )
