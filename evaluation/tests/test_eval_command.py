"""Tests for the `eval` management command's subcommands (task 7.2, task 2.2)."""

import json
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

import evaluation.selectors as evaluation_selectors
from contracts.models import Contract
from evaluation.models import EvalRun
from evaluation.selectors import compute_manifest_hash

pytestmark = pytest.mark.django_db


def _write_manifest(root, *, dataset_version, heldout_engagement_ids, manifest_sha256=None):
    manifest_dir = root / "eval" / dataset_version
    manifest_dir.mkdir(parents=True, exist_ok=True)
    if manifest_sha256 is None:
        manifest_sha256 = compute_manifest_hash(heldout_engagement_ids)
    payload = {
        "dataset_version": dataset_version,
        "heldout_engagement_ids": heldout_engagement_ids,
        "manifest_sha256": manifest_sha256,
    }
    (manifest_dir / "heldout_manifest.json").write_text(json.dumps(payload), encoding="utf-8")


class TestEvalRunCommandSuccess:
    def test_matching_manifest_prints_metrics_and_exits_zero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(evaluation_selectors, "_FIXTURES_ROOT", tmp_path)
        _write_manifest(tmp_path, dataset_version="cmd-ok", heldout_engagement_ids=[])

        call_command("eval", "run", "--dataset=eval/cmd-ok")

        captured = capsys.readouterr()
        assert "EvalRun" in captured.out
        assert "precision_recall_f1" in captured.out
        assert EvalRun.objects.filter(dataset_version="cmd-ok").exists()

    def test_bare_dataset_version_without_eval_prefix_also_works(self, tmp_path, monkeypatch):
        monkeypatch.setattr(evaluation_selectors, "_FIXTURES_ROOT", tmp_path)
        _write_manifest(tmp_path, dataset_version="cmd-bare", heldout_engagement_ids=[])

        call_command("eval", "run", "--dataset=cmd-bare")

        assert EvalRun.objects.filter(dataset_version="cmd-bare").exists()


class TestEvalRunCommandMismatchedManifest:
    def test_mismatched_manifest_exits_nonzero_with_no_eval_run_persisted(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(evaluation_selectors, "_FIXTURES_ROOT", tmp_path)
        _write_manifest(
            tmp_path,
            dataset_version="cmd-bad",
            heldout_engagement_ids=["synthetic-cmd-bad-001"],
            manifest_sha256="0" * 64,  # deliberately wrong
        )

        before_count = EvalRun.objects.count()
        with pytest.raises(CommandError):
            call_command("eval", "run", "--dataset=eval/cmd-bad")

        assert EvalRun.objects.count() == before_count
        assert not EvalRun.objects.filter(dataset_version="cmd-bad").exists()


def _phrasing_response(count: int = 5) -> dict:
    return {"clauses": [{"text": f"Generic clause prose number {i}."} for i in range(count)]}


class TestEvalGenerateDatasetCommand:
    """Tests for `eval generate-dataset` (task 2.2)."""

    @patch("core.llm_client.get_structured_completion")
    def test_generates_labels_and_writes_export_file(self, mock_completion, tmp_path):
        mock_completion.return_value = _phrasing_response()
        export_path = tmp_path / "dataset" / "cmd-gen" / "contracts.json"

        call_command(
            "eval",
            "generate-dataset",
            "--dataset=eval/cmd-gen",
            "--count=30",
            f"--export={export_path}",
        )

        assert Contract.objects.filter(engagement_id__startswith="synthetic-cmd-gen-").count() == 30

        assert export_path.exists()
        snapshot = json.loads(export_path.read_text(encoding="utf-8"))
        assert snapshot["dataset_version"] == "cmd-gen"
        assert len(snapshot["contracts"]) == 30
        for entry in snapshot["contracts"]:
            assert entry["engagement_id"].startswith("synthetic-cmd-gen-")
            assert entry["raw_text"]
            assert entry["labels"]

    @patch("core.llm_client.get_structured_completion")
    def test_bare_dataset_version_without_eval_prefix_also_works(self, mock_completion, tmp_path):
        mock_completion.return_value = _phrasing_response()
        export_path = tmp_path / "contracts.json"

        call_command(
            "eval",
            "generate-dataset",
            "--dataset=cmd-gen-bare",
            "--count=30",
            f"--export={export_path}",
        )

        snapshot = json.loads(export_path.read_text(encoding="utf-8"))
        assert snapshot["dataset_version"] == "cmd-gen-bare"
        assert len(snapshot["contracts"]) == 30
