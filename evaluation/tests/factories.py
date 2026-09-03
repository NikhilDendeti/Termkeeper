import factory
from factory.django import DjangoModelFactory

# Re-exported so `evaluation` tests can build a Contract/Clause without
# depending on `contracts.tests` paths directly - `contracts` factories are
# the single source of truth for those models.
from contracts.tests.factories import ClauseFactory, ContractFactory  # noqa: F401
from evaluation.dataset_types import SyntheticContractParams
from evaluation.models import EvalLabel, EvalLabelType, EvalRun


class SyntheticContractParamsFactory(factory.Factory):
    class Meta:
        model = SyntheticContractParams

    engagement_type = "fixed-fee"
    domain = "dev"
    clause_severity_profile = "fair"
    phrasing_style = "plain"
    razorpay_reference_type = "payout"
    seed = factory.Sequence(lambda n: 1000 + n)


class EvalLabelFactory(DjangoModelFactory):
    class Meta:
        model = EvalLabel

    contract = factory.SubFactory(ContractFactory)
    clause = factory.SubFactory(ClauseFactory)
    label_type = EvalLabelType.RISK_SEVERITY
    ground_truth_value = factory.LazyFunction(
        lambda: {
            "clause_type": "payment_schedule",
            "risky": True,
            "severity": 4,
            "rationale": "The payment_schedule clause imposes a delayed payout cadence.",
            "needs_human_review": False,
        }
    )
    annotator = "synthetic-rubric-v1"


class EvalRunFactory(DjangoModelFactory):
    class Meta:
        model = EvalRun

    dataset_version = "v1"
    fixture_version = "v1"
    precision_recall_f1 = factory.LazyFunction(
        lambda: {
            "risk_severity": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "mismatch_present": {"precision": 1.0, "recall": 1.0},
        }
    )
    severity_calibration_score = 1.0
    cost_report = factory.LazyFunction(dict)
    false_positive_cost_note = "5.0 reviewer-minutes assumed per dismissed flag."
    pipeline_version = "unknown"
    prompt_version = "clause-segmentation-v1"
