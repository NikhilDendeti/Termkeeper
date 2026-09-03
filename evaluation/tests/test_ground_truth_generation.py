"""Tests for `evaluation.services.generate_clause_ground_truth` (tasks 2.1, 2.3, 2.6)."""

from evaluation.dataset_types import ClauseSeverityProfile, SyntheticContractParams
from evaluation.services import compute_overall_risk_tier, generate_clause_ground_truth

_BASE_PARAMS = SyntheticContractParams(
    engagement_type="fixed-fee",
    domain="dev",
    clause_severity_profile="fair",
    phrasing_style="plain",
    razorpay_reference_type="payout",
    seed=4242,
)


class TestGroundTruthIsDeterministic:
    """Requirement: Ground truth generated before prose (task 2.1)."""

    def test_two_calls_with_same_seed_produce_identical_ground_truth(self):
        first = generate_clause_ground_truth(params=_BASE_PARAMS)
        second = generate_clause_ground_truth(params=_BASE_PARAMS)

        assert first == second

    def test_different_seed_can_produce_different_ground_truth(self):
        other_params = SyntheticContractParams(
            engagement_type=_BASE_PARAMS.engagement_type,
            domain=_BASE_PARAMS.domain,
            clause_severity_profile=_BASE_PARAMS.clause_severity_profile,
            phrasing_style=_BASE_PARAMS.phrasing_style,
            razorpay_reference_type=_BASE_PARAMS.razorpay_reference_type,
            seed=_BASE_PARAMS.seed + 1,
        )

        first = generate_clause_ground_truth(params=_BASE_PARAMS)
        second = generate_clause_ground_truth(params=other_params)

        assert first != second


class TestGroundTruthShape:
    def test_every_clause_carries_all_rubric_fields(self):
        ground_truths = generate_clause_ground_truth(params=_BASE_PARAMS)

        assert len(ground_truths) == 5
        for ground_truth in ground_truths:
            assert ground_truth.clause_type
            assert isinstance(ground_truth.risky, bool)
            assert 1 <= ground_truth.severity <= 5
            assert ground_truth.rationale
            assert isinstance(ground_truth.needs_human_review, bool)


class TestSeverityVariesWithinOneContract:
    """Requirement: Severity varies within one contract (task 2.3)."""

    def test_a_fair_profile_contract_can_still_contain_an_exploitative_clause(self):
        found_mixed_contract = False
        for seed in range(1000, 1200):
            params = SyntheticContractParams(
                engagement_type="fixed-fee",
                domain="dev",
                clause_severity_profile=ClauseSeverityProfile.FAIR.value,
                phrasing_style="plain",
                razorpay_reference_type="payout",
                seed=seed,
            )
            ground_truths = generate_clause_ground_truth(params=params)
            profiles = {gt.severity_profile for gt in ground_truths}
            if (
                ClauseSeverityProfile.DELIBERATELY_EXPLOITATIVE.value in profiles
                and ClauseSeverityProfile.FAIR.value in profiles
            ):
                found_mixed_contract = True
                break

        assert found_mixed_contract, (
            "expected at least one fair-profile contract, across a range of seeds, to "
            "still contain an independently-assigned deliberately-exploitative clause"
        )


class TestFloorRuleForcesCriticalTier:
    """Requirement: Per-contract risk tier with a floor rule (task 2.6)."""

    def test_two_severity_four_clauses_with_no_severity_five_is_still_critical(self):
        assert compute_overall_risk_tier(clause_severities=[4, 4, 1, 1, 2]) == "critical"

    def test_a_single_severity_five_clause_alone_is_critical(self):
        assert compute_overall_risk_tier(clause_severities=[5, 1, 1, 1, 1]) == "critical"

    def test_a_single_severity_four_clause_alone_is_not_critical(self):
        assert compute_overall_risk_tier(clause_severities=[4, 1, 1, 1, 1]) == "high"

    def test_all_low_severity_clauses_is_low(self):
        assert compute_overall_risk_tier(clause_severities=[1, 1, 1, 1, 1]) == "low"
