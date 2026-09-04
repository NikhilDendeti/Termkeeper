"""Tests for evaluation.selectors.get_latest_eval_run."""

from __future__ import annotations

import pytest

from evaluation.selectors import get_latest_eval_run
from evaluation.tests.factories import EvalRunFactory

pytestmark = pytest.mark.django_db


class TestGetLatestEvalRun:
    def test_no_eval_run_yet_returns_none(self):
        assert get_latest_eval_run() is None

    def test_single_eval_run_is_returned(self):
        eval_run = EvalRunFactory()

        assert get_latest_eval_run() == eval_run

    def test_most_recently_run_eval_run_is_returned_not_the_first_created(self):
        # EvalRun.Meta.ordering = ["-run_at"]; run_at is auto_now_add, so
        # creation order is run_at order - the later-created row must win.
        EvalRunFactory(dataset_version="v1")
        newest = EvalRunFactory(dataset_version="v2")

        latest = get_latest_eval_run()

        assert latest is not None
        assert latest.id == newest.id
        assert latest.dataset_version == "v2"
