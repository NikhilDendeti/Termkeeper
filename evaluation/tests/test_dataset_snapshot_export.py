"""Tests for `evaluation.services.export_dataset_snapshot` (task 2.1).

See specs/evaluation/dataset-snapshot-export/spec.md (Requirement: Dataset
export is portable and complete).
"""

from unittest.mock import patch

import pytest

from contracts.models import Contract
from evaluation.services import (
    export_dataset_snapshot,
    generate_dataset,
    load_razorpay_fixture_scenarios,
)

pytestmark = pytest.mark.django_db


def _phrasing_response(count: int = 5) -> dict:
    return {"clauses": [{"text": f"Generic clause prose number {i}."} for i in range(count)]}


def _mixed_completion_side_effect(system_prompt, user_content, schema, *, prompt_version):
    """Routes to the right canned response for whichever Claude call fires.

    Used only by the fixture-exclusion test below, which drives both
    `generate_dataset` (phrasing calls) and `load_razorpay_fixture_scenarios`
    (mismatch-description calls) through one mocked
    `core.llm_client.get_structured_completion`.
    """
    if prompt_version == "synthetic-contract-phrasing-v1":
        return _phrasing_response()
    # mismatch-description-v1: quotes deliberately don't verify, so
    # detect_mismatches falls back to its deterministic templated
    # description - fine, this test doesn't assert on description text.
    return {
        "description": "Contract-stated term does not match observed Razorpay data.",
        "expected_quote": "x",
        "actual_quote": "x",
    }


class TestExportContainsEveryGeneratedContract:
    """Requirement: Dataset export is portable and complete - Scenario: Export
    contains every generated contract (task 2.1)."""

    @patch("core.llm_client.get_structured_completion")
    def test_export_has_exactly_n_entries_with_raw_text_and_labels(self, mock_completion):
        mock_completion.return_value = _phrasing_response()

        contracts = generate_dataset(dataset_version="export-small", count=30)

        snapshot = export_dataset_snapshot(dataset_version="export-small")

        assert snapshot["dataset_version"] == "export-small"
        assert len(snapshot["contracts"]) == 30

        exported_engagement_ids = {entry["engagement_id"] for entry in snapshot["contracts"]}
        assert exported_engagement_ids == {contract.engagement_id for contract in contracts}

        for entry in snapshot["contracts"]:
            assert entry["raw_text"]
            assert entry["engagement_id"].startswith("synthetic-export-small-")
            # 5 clause-level labels + 1 contract-level overall_risk_tier label.
            assert len(entry["labels"]) == 6
            clause_labels = [
                label for label in entry["labels"] if label["clause_sequence_index"] is not None
            ]
            assert len(clause_labels) == 5
            contract_level = [
                label for label in entry["labels"] if label["clause_sequence_index"] is None
            ]
            assert len(contract_level) == 1
            assert "overall_risk_tier" in contract_level[0]["ground_truth_value"]

    @patch("core.llm_client.get_structured_completion")
    def test_params_are_recomputed_deterministically_per_contract(self, mock_completion):
        mock_completion.return_value = _phrasing_response()

        generate_dataset(dataset_version="export-params", count=30)

        first_export = export_dataset_snapshot(dataset_version="export-params")
        second_export = export_dataset_snapshot(dataset_version="export-params")

        assert first_export["contracts"] == second_export["contracts"]

        first_entry = next(
            entry
            for entry in first_export["contracts"]
            if entry["engagement_id"] == "synthetic-export-params-001"
        )
        # sequence_number=1 -> index=0 -> seed=1000.
        assert first_entry["params"]["seed"] == 1000
        assert first_entry["params"].keys() == {
            "engagement_type",
            "domain",
            "clause_severity_profile",
            "phrasing_style",
            "razorpay_reference_type",
            "seed",
        }

    def test_empty_dataset_version_exports_zero_contracts(self):
        snapshot = export_dataset_snapshot(dataset_version="never-generated")

        assert snapshot["dataset_version"] == "never-generated"
        assert snapshot["contracts"] == []


class TestExportExcludesFixtureScenarioContracts:
    """Fixture-matrix contracts (`synthetic-{version}-fixture-*`) are a
    separate, differently-namespaced artifact and must never appear in a
    main-dataset export."""

    @patch(
        "core.llm_client.get_structured_completion",
        side_effect=_mixed_completion_side_effect,
    )
    def test_fixture_scenario_contracts_are_not_exported(self, mock_completion):
        generate_dataset(dataset_version="export-mix", count=30)

        load_razorpay_fixture_scenarios(fixture_version="v1", dataset_version="export-mix")

        fixture_contracts = Contract.objects.filter(
            engagement_id__startswith="synthetic-export-mix-fixture-"
        )
        assert fixture_contracts.exists()

        snapshot = export_dataset_snapshot(dataset_version="export-mix")

        assert len(snapshot["contracts"]) == 30
        for entry in snapshot["contracts"]:
            assert "fixture" not in entry["engagement_id"]
