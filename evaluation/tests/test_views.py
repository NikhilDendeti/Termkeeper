"""Tests for evaluation.views.LatestEvalRunAPIView."""

from __future__ import annotations

import pytest
from django.urls import reverse

from evaluation.tests.factories import EvalRunFactory

pytestmark = pytest.mark.django_db


class TestLatestEvalRunAPIView:
    def test_no_eval_run_yet_returns_200_with_an_explicit_null_eval_run_not_an_error(
        self, client
    ):
        response = client.get(reverse("latest-eval-run"))

        assert response.status_code == 200
        body = response.json()
        assert body == {"eval_run": None}

    def test_returns_the_latest_eval_run_serialized(self, client):
        EvalRunFactory(dataset_version="v1")
        newest = EvalRunFactory(dataset_version="v2", severity_calibration_score=0.9)

        response = client.get(reverse("latest-eval-run"))

        assert response.status_code == 200
        body = response.json()["eval_run"]
        assert body["id"] == str(newest.id)
        assert body["dataset_version"] == "v2"
        assert body["severity_calibration_score"] == 0.9
        assert "precision_recall_f1" in body
        assert "cost_report" in body

    def test_url_resolves(self):
        url = reverse("latest-eval-run")
        assert url.endswith("/eval-runs/latest/")
