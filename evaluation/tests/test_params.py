"""Tests for `SyntheticContractParams` (task 1.3)."""

import pytest

from evaluation.dataset_types import SyntheticContractParams


class TestSyntheticContractParamsValidation:
    def test_valid_params_construct_successfully(self):
        params = SyntheticContractParams(
            engagement_type="fixed-fee",
            domain="dev",
            clause_severity_profile="fair",
            phrasing_style="plain",
            razorpay_reference_type="payout",
            seed=1,
        )
        assert params.seed == 1

    def test_out_of_taxonomy_engagement_type_rejected(self):
        with pytest.raises(ValueError):
            SyntheticContractParams(
                engagement_type="not-a-real-engagement-type",
                domain="dev",
                clause_severity_profile="fair",
                phrasing_style="plain",
                razorpay_reference_type="payout",
                seed=1,
            )

    def test_out_of_taxonomy_domain_rejected(self):
        with pytest.raises(ValueError):
            SyntheticContractParams(
                engagement_type="fixed-fee",
                domain="not-a-real-domain",
                clause_severity_profile="fair",
                phrasing_style="plain",
                razorpay_reference_type="payout",
                seed=1,
            )

    def test_out_of_taxonomy_clause_severity_profile_rejected(self):
        with pytest.raises(ValueError):
            SyntheticContractParams(
                engagement_type="fixed-fee",
                domain="dev",
                clause_severity_profile="not-a-real-profile",
                phrasing_style="plain",
                razorpay_reference_type="payout",
                seed=1,
            )

    def test_out_of_taxonomy_phrasing_style_rejected(self):
        with pytest.raises(ValueError):
            SyntheticContractParams(
                engagement_type="fixed-fee",
                domain="dev",
                clause_severity_profile="fair",
                phrasing_style="not-a-real-style",
                razorpay_reference_type="payout",
                seed=1,
            )

    def test_out_of_taxonomy_razorpay_reference_type_rejected(self):
        with pytest.raises(ValueError):
            SyntheticContractParams(
                engagement_type="fixed-fee",
                domain="dev",
                clause_severity_profile="fair",
                phrasing_style="plain",
                razorpay_reference_type="not-a-real-reference-type",
                seed=1,
            )
