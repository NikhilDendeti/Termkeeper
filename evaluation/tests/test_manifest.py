"""Tests for the held-out manifest (tasks 3.2, 3.3, 3.4)."""

import json

import pytest

import evaluation.selectors as evaluation_selectors
from evaluation.models import EvalRun
from evaluation.selectors import compute_manifest_hash, get_heldout_manifest
from evaluation.services import ManifestIntegrityError, run_eval

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
    return payload


class TestCommittedV1Manifest:
    """Requirement: the committed eval/v1 manifest is internally consistent (task 3.2)."""

    def test_committed_manifest_hash_matches_its_own_id_list(self):
        manifest = get_heldout_manifest(dataset_version="v1")

        recomputed = compute_manifest_hash(manifest.heldout_engagement_ids)

        assert recomputed == manifest.recorded_hash
        assert manifest.dataset_version == "v1"
        assert len(manifest.heldout_engagement_ids) > 0


class TestGetHeldoutManifestRecomputesHashCorrectly:
    """Task 3.2: get_heldout_manifest correctly recomputes the hash over the file's own id list."""

    def test_recomputed_hash_matches_a_freshly_authored_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(evaluation_selectors, "_FIXTURES_ROOT", tmp_path)
        ids = ["synthetic-test-001", "synthetic-test-002"]
        _write_manifest(tmp_path, dataset_version="test", heldout_engagement_ids=ids)

        manifest = get_heldout_manifest(dataset_version="test")

        assert compute_manifest_hash(manifest.heldout_engagement_ids) == manifest.recorded_hash


class TestMismatchedManifestBlocksTheRun:
    """Requirement: Mismatched manifest blocks the run (task 3.3)."""

    def test_hand_edited_id_list_aborts_with_no_eval_run_persisted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(evaluation_selectors, "_FIXTURES_ROOT", tmp_path)
        ids = ["synthetic-test-001", "synthetic-test-002"]
        # Author the manifest with a correct hash, then hand-edit the id
        # list afterward without recomputing the checksum - simulating a
        # contributor who added a contract without updating manifest_sha256.
        payload = _write_manifest(tmp_path, dataset_version="test", heldout_engagement_ids=ids)
        payload["heldout_engagement_ids"].append("synthetic-test-003")
        (tmp_path / "eval" / "test" / "heldout_manifest.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

        before_count = EvalRun.objects.count()
        with pytest.raises(ManifestIntegrityError):
            run_eval(dataset_version="test")

        assert EvalRun.objects.count() == before_count


class TestMatchingManifestProceeds:
    """Requirement: Matching manifest proceeds (task 3.4)."""

    def test_matching_manifest_with_no_resolvable_contract_raises_a_distinct_error(
        self, tmp_path, monkeypatch
    ):
        # A matching manifest whose ids resolve to no Contract row is still
        # an integrity failure (a different one - drift between the
        # manifest and the generated dataset) - proving the hash check
        # alone isn't what's gating scoring.
        monkeypatch.setattr(evaluation_selectors, "_FIXTURES_ROOT", tmp_path)
        ids = ["synthetic-test-does-not-exist-001"]
        _write_manifest(tmp_path, dataset_version="test", heldout_engagement_ids=ids)

        before_count = EvalRun.objects.count()
        with pytest.raises(ManifestIntegrityError):
            run_eval(dataset_version="test")
        assert EvalRun.objects.count() == before_count

    def test_matching_manifest_with_no_heldout_contracts_still_persists_an_eval_run(
        self, tmp_path, monkeypatch
    ):
        # An empty (but internally consistent) manifest is the simplest
        # "matching manifest" case: nothing to abort on, so run_eval must
        # proceed all the way to persisting an EvalRun row.
        monkeypatch.setattr(evaluation_selectors, "_FIXTURES_ROOT", tmp_path)
        _write_manifest(tmp_path, dataset_version="test", heldout_engagement_ids=[])

        before_count = EvalRun.objects.count()
        eval_run = run_eval(dataset_version="test")

        assert EvalRun.objects.count() == before_count + 1
        assert eval_run.dataset_version == "test"
