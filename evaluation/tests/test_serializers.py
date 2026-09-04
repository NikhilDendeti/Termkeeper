"""Tests for evaluation.serializers.EvalRunSerializer."""

from __future__ import annotations

import pytest

from evaluation.serializers import EvalRunSerializer
from evaluation.tests.factories import EvalRunFactory

pytestmark = pytest.mark.django_db


class TestEvalRunSerializer:
    def test_serializes_every_field_of_a_real_eval_run(self):
        eval_run = EvalRunFactory(
            dataset_version="v1",
            fixture_version="v1",
            severity_calibration_score=0.875,
            false_positive_cost_note="5.0 reviewer-minutes assumed per dismissed flag.",
            pipeline_version="abc1234",
            prompt_version="clause-segmentation-v1,risk-scoring-v1",
        )

        data = EvalRunSerializer(instance=eval_run).data

        assert data["id"] == str(eval_run.id)
        assert data["dataset_version"] == "v1"
        assert data["fixture_version"] == "v1"
        assert data["severity_calibration_score"] == 0.875
        assert data["false_positive_cost_note"] == (
            "5.0 reviewer-minutes assumed per dismissed flag."
        )
        assert data["pipeline_version"] == "abc1234"
        assert data["prompt_version"] == "clause-segmentation-v1,risk-scoring-v1"
        assert "run_at" in data
        assert data["precision_recall_f1"] == eval_run.precision_recall_f1
        assert data["cost_report"] == eval_run.cost_report

    def test_nested_precision_recall_f1_and_cost_report_survive_round_trip(self):
        eval_run = EvalRunFactory(
            precision_recall_f1={
                "risk_severity": {"precision": 0.9, "recall": 0.8, "f1": 0.847},
                "mismatch_present": {"precision": 1.0, "recall": 0.75},
            },
            cost_report={
                "fp_count": 2,
                "fn_count": 1,
                "by_clause_type": {"termination": {"fp_count": 1, "fn_count": 0}},
            },
        )

        data = EvalRunSerializer(instance=eval_run).data

        assert data["precision_recall_f1"]["risk_severity"]["f1"] == 0.847
        assert data["cost_report"]["by_clause_type"]["termination"]["fp_count"] == 1
