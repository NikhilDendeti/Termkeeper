"""Tests for the deterministic severity formula (tasks 4.1-4.4)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from contracts.models import ClauseType
from contracts.tests.factories import ClauseFactory
from risk_scoring.models import SeverityChoices
from risk_scoring.services import CRITICALITY_WEIGHTS, _compute_severity, score_clause

_BAND_RANK = {
    SeverityChoices.LOW.value: 0,
    SeverityChoices.MEDIUM.value: 1,
    SeverityChoices.HIGH.value: 2,
    SeverityChoices.CRITICAL.value: 3,
}


class TestCriticalityWeights:
    def test_every_scorable_clause_type_has_a_criticality_weight(self):
        scorable_types = {
            choice.value
            for choice in ClauseType
            if choice != ClauseType.NEEDS_HUMAN_REVIEW
        }
        assert set(CRITICALITY_WEIGHTS) == scorable_types


class TestSeverityFormulaTableDriven:
    """Task 4.1: at least one clause_type per weight tier."""

    @pytest.mark.parametrize(
        "clause_type, asymmetry_score, has_mismatch, expected",
        [
            # criticality=1.0
            ("payment_schedule", 0.9, False, "critical"),
            ("penalty_late_fee", 0.6, False, "high"),
            # criticality=0.8
            ("termination", 0.5, False, "medium"),
            ("indemnity", 0.2, False, "low"),
            # criticality=0.6
            ("auto_renewal", 0.9, False, "high"),
            # criticality=0.5
            ("dispute_resolution", 0.9, False, "medium"),
            # criticality=0.3
            ("other", 0.9, False, "medium"),
            ("other", 0.1, False, "low"),
        ],
    )
    def test_formula_bands_match_expected_severity(
        self, clause_type, asymmetry_score, has_mismatch, expected
    ):
        severity = _compute_severity(
            clause_type=clause_type, asymmetry_score=asymmetry_score, has_mismatch=has_mismatch
        )
        assert severity == expected


class TestSeverityMonotonicWithAsymmetryMagnitude:
    """Task 4.2: higher asymmetry never lowers severity, all else fixed."""

    @pytest.mark.parametrize("clause_type", list(CRITICALITY_WEIGHTS))
    @pytest.mark.parametrize("has_mismatch", [False, True])
    def test_severity_band_never_decreases_as_asymmetry_grows(self, clause_type, has_mismatch):
        scores = [0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        bands = [
            _BAND_RANK[
                _compute_severity(
                    clause_type=clause_type, asymmetry_score=score, has_mismatch=has_mismatch
                )
            ]
            for score in scores
        ]
        assert bands == sorted(bands)


class TestMismatchLinkageRaisesOrHoldsSeverity:
    """Task 4.3: a linked MismatchFlag never lowers severity, all else fixed."""

    @pytest.mark.parametrize("clause_type", list(CRITICALITY_WEIGHTS))
    @pytest.mark.parametrize("asymmetry_score", [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0])
    def test_mismatch_linked_band_is_at_least_as_high(self, clause_type, asymmetry_score):
        without_mismatch = _compute_severity(
            clause_type=clause_type, asymmetry_score=asymmetry_score, has_mismatch=False
        )
        with_mismatch = _compute_severity(
            clause_type=clause_type, asymmetry_score=asymmetry_score, has_mismatch=True
        )
        assert _BAND_RANK[with_mismatch] >= _BAND_RANK[without_mismatch]


@pytest.mark.django_db
class TestSeverityTaxonomyAcrossEveryCodePath:
    """Task 4.4: severity is always one of the five defined labels."""

    _ALL_LABELS = {choice.value for choice in SeverityChoices}

    def test_short_circuit_path_uses_a_defined_label(self):
        clause = ClauseFactory(clause_type=None, clause_text="Boilerplate.")

        assessment = score_clause(clause=clause)

        assert assessment.severity in self._ALL_LABELS

    @patch("core.llm_client.get_structured_completion")
    def test_forced_review_path_uses_a_defined_label(self, mock_completion):
        clause_text = "Some clause text with no quotable overlap at all here."
        mock_completion.return_value = {
            "sentences": [{"text": "claim", "quote": "not present anywhere"}],
            "asymmetry_score": 0.5,
            "suggested_rewrite": None,
        }
        clause = ClauseFactory(clause_type="termination", clause_text=clause_text)

        assessment = score_clause(clause=clause)

        assert assessment.severity in self._ALL_LABELS
        assert assessment.severity == SeverityChoices.NEEDS_HUMAN_REVIEW.value

    @patch("core.llm_client.get_structured_completion")
    def test_formula_derived_path_uses_a_defined_label(self, mock_completion):
        clause_text = "Vendor shall indemnify Client against all third-party claims."
        mock_completion.return_value = {
            "sentences": [
                {
                    "text": "Vendor bears the full indemnification burden.",
                    "quote": "Vendor shall indemnify Client against all third-party claims",
                }
            ],
            "asymmetry_score": 0.7,
            "suggested_rewrite": "Share indemnification obligations more evenly.",
        }
        clause = ClauseFactory(clause_type="indemnity", clause_text=clause_text)

        assessment = score_clause(clause=clause)

        assert assessment.severity in self._ALL_LABELS
        assert assessment.severity != SeverityChoices.NEEDS_HUMAN_REVIEW.value
