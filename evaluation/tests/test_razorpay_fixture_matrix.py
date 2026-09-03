"""Tests for the Razorpay test-mode fixture matrix (tasks 4.1-4.5)."""

from unittest.mock import patch

import pytest
import razorpay

from evaluation.models import EvalLabel
from evaluation.selectors import get_razorpay_fixture_scenarios
from evaluation.services import load_razorpay_fixture_scenarios
from razorpay_integration.models import MismatchFlag, MismatchType

pytestmark = pytest.mark.django_db

_DESCRIPTION_RESPONSE = {
    "description": "Contract-stated term does not match observed Razorpay data.",
    "expected_quote": "x",
    "actual_quote": "x",
}


def _description_side_effect(system_prompt, user_content, schema, *, prompt_version):
    # Always fails quote verification (its quotes aren't real substrings),
    # so the deterministic templated fallback is used instead - the point
    # of these tests is mismatch *detection*, not description wording.
    return _DESCRIPTION_RESPONSE


class TestMinimumMatrixSizeAndCoverage:
    """Requirement: Minimum fixture matrix size and mismatch-type coverage (task 4.1)."""

    def test_matrix_has_at_least_ten_scenarios(self):
        scenarios = get_razorpay_fixture_scenarios(fixture_version="v1")
        assert len(scenarios) >= 10

    def test_every_mismatch_type_is_covered(self):
        scenarios = get_razorpay_fixture_scenarios(fixture_version="v1")
        covered = {s["expected_mismatch_type"] for s in scenarios if s["expected_mismatch_type"]}
        all_mismatch_types = {choice.value for choice in MismatchType}
        assert all_mismatch_types <= covered


class TestControlProducesNoFlag:
    """Requirement: True-negative control scenario (task 4.2)."""

    @patch("core.llm_client.get_structured_completion", side_effect=_description_side_effect)
    def test_true_negative_scenarios_raise_no_mismatch_flag(self, mock_completion):
        load_razorpay_fixture_scenarios(fixture_version="v1", dataset_version="it-fixtures")

        true_negative_labels = EvalLabel.objects.filter(
            contract__engagement_id__startswith="synthetic-it-fixtures-fixture-true_negative"
        )
        assert true_negative_labels.exists()
        for label in true_negative_labels:
            assert not MismatchFlag.objects.filter(extracted_term__clause=label.clause).exists()


class TestUnverifiableTermDeclinesRatherThanFabricates:
    """Requirement: Deliberately unverifiable scenario (task 4.3)."""

    @patch("core.llm_client.get_structured_completion", side_effect=_description_side_effect)
    def test_unverifiable_scenarios_get_trigger_condition_unverifiable_not_a_fabricated_flag(
        self, mock_completion
    ):
        load_razorpay_fixture_scenarios(fixture_version="v1", dataset_version="it-fixtures")

        unverifiable_labels = EvalLabel.objects.filter(
            contract__engagement_id__startswith="synthetic-it-fixtures-fixture-unverifiable"
        )
        assert unverifiable_labels.exists()
        for label in unverifiable_labels:
            flags = MismatchFlag.objects.filter(extracted_term__clause=label.clause)
            assert flags.count() == 1
            assert flags.first().mismatch_type == MismatchType.TRIGGER_CONDITION_UNVERIFIABLE.value


class TestNoLiveResourceCallsDuringFixtureEvaluation:
    """Requirement: Fixtures are test-mode only (task 4.5)."""

    @patch("core.llm_client.get_structured_completion", side_effect=_description_side_effect)
    def test_loading_the_matrix_never_dispatches_a_real_razorpay_request(
        self, mock_completion, monkeypatch
    ):
        def _fail_if_called(self, method, path, **options):
            raise AssertionError(
                f"fixture loading must never dispatch a real Razorpay request, got "
                f"{method.upper()} {path}"
            )

        monkeypatch.setattr(razorpay.Client, "request", _fail_if_called)

        # Must complete without ever exercising the real SDK transport -
        # every scenario's Razorpay data comes from the fixture matrix's own
        # committed payload via `_FixtureRazorpayConnector`, never a live call.
        labels = load_razorpay_fixture_scenarios(
            fixture_version="v1", dataset_version="it-fixtures-guardrail"
        )
        assert len(labels) >= 10


class TestFixtureVersionRecordedOnEvalRun:
    """Requirement: EvalRun records the fixture version used (task 4.4)."""

    @patch("core.llm_client.get_structured_completion", side_effect=_description_side_effect)
    def test_eval_run_records_the_fixture_version(self, mock_completion, tmp_path, monkeypatch):
        import json

        import evaluation.selectors as evaluation_selectors
        from evaluation.selectors import compute_manifest_hash
        from evaluation.services import run_eval

        monkeypatch.setattr(evaluation_selectors, "_FIXTURES_ROOT", tmp_path)
        manifest_dir = tmp_path / "eval" / "it-fixture-version"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "heldout_manifest.json").write_text(
            json.dumps(
                {
                    "dataset_version": "it-fixture-version",
                    "heldout_engagement_ids": [],
                    "manifest_sha256": compute_manifest_hash([]),
                }
            ),
            encoding="utf-8",
        )

        eval_run = run_eval(dataset_version="it-fixture-version", fixture_version="v1")

        assert eval_run.fixture_version == "v1"
