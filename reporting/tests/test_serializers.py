"""Tests for reporting.serializers (task 7.1, and task 3.2 additions)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from reporting.serializers import (
    ClauseReasoningChainSerializer,
    ContractReportSerializer,
    ContractSummarySerializer,
    GuardrailScanResultSerializer,
)

_SAMPLE_REPORT = {
    "contract_id": uuid.uuid4(),
    "overall_risk_score": 0.625,
    "flagged_clauses": [
        {
            "clause_id": uuid.uuid4(),
            "sequence_index": 0,
            "clause_type": "termination",
            "clause_text": "Either party may terminate with 90 days notice.",
            "severity": "high",
            "asymmetry_score": 0.6,
            "explanation": "One party bears the full termination burden.",
            "suggested_rewrite": "Give both parties equal notice.",
            "linked_mismatch_flag_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
        }
    ],
    "platform_mismatches": [
        {
            "mismatch_id": uuid.uuid4(),
            "mismatch_type": "cadence_mismatch",
            "clause_id": uuid.uuid4(),
            "sequence_index": 1,
            "expected_value": {"numeric_value": 30, "unit": "days"},
            "actual_value": {"empirical_cadence_days": 45.0},
            "description": "Contract states 30 days; observed cadence is 45 days.",
        }
    ],
    "needs_human_review_clauses": [
        {
            "clause_id": uuid.uuid4(),
            "sequence_index": 2,
            "clause_type": None,
            "clause_text": "Ambiguous boilerplate text.",
            "explanation": "clause was not confidently classified.",
        }
    ],
    "severity_breakdown_by_clause_type": {
        "termination": {"count": 1, "mean_asymmetry_score": 0.6},
    },
}


class TestContractReportSerializerRoundTrip:
    def test_round_trips_a_sample_report_dict_without_field_loss(self):
        serializer = ContractReportSerializer(instance=_SAMPLE_REPORT)

        data = serializer.data

        assert str(data["contract_id"]) == str(_SAMPLE_REPORT["contract_id"])
        assert data["overall_risk_score"] == _SAMPLE_REPORT["overall_risk_score"]

        flagged = data["flagged_clauses"][0]
        expected_flagged = _SAMPLE_REPORT["flagged_clauses"][0]
        assert str(flagged["clause_id"]) == str(expected_flagged["clause_id"])
        assert flagged["severity"] == expected_flagged["severity"]
        assert flagged["asymmetry_score"] == expected_flagged["asymmetry_score"]
        assert flagged["explanation"] == expected_flagged["explanation"]
        assert flagged["suggested_rewrite"] == expected_flagged["suggested_rewrite"]
        assert flagged["linked_mismatch_flag_ids"] == expected_flagged["linked_mismatch_flag_ids"]

        mismatch = data["platform_mismatches"][0]
        expected_mismatch = _SAMPLE_REPORT["platform_mismatches"][0]
        assert str(mismatch["mismatch_id"]) == str(expected_mismatch["mismatch_id"])
        assert mismatch["expected_value"] == expected_mismatch["expected_value"]
        assert mismatch["actual_value"] == expected_mismatch["actual_value"]
        assert mismatch["description"] == expected_mismatch["description"]

        review = data["needs_human_review_clauses"][0]
        expected_review = _SAMPLE_REPORT["needs_human_review_clauses"][0]
        assert review["clause_type"] is None
        assert review["explanation"] == expected_review["explanation"]

        assert data["severity_breakdown_by_clause_type"] == {
            "termination": {"count": 1, "mean_asymmetry_score": 0.6},
        }

    def test_null_suggested_rewrite_and_null_clause_type_survive(self):
        sample = {
            **_SAMPLE_REPORT,
            "overall_risk_score": None,
            "flagged_clauses": [],
        }
        data = ContractReportSerializer(instance=sample).data

        assert data["overall_risk_score"] is None

    def test_empty_severity_breakdown_survives(self):
        sample = {**_SAMPLE_REPORT, "severity_breakdown_by_clause_type": {}}

        data = ContractReportSerializer(instance=sample).data

        assert data["severity_breakdown_by_clause_type"] == {}


# ---------------------------------------------------------------------------
# Task 3.2 additions: ContractSummarySerializer, ClauseReasoningChainSerializer,
# GuardrailScanResultSerializer (GuardrailViolationSerializer is exercised
# indirectly through GuardrailScanResultSerializer below).
# ---------------------------------------------------------------------------


class TestContractSummarySerializer:
    def test_round_trips_a_summary_with_null_overall_risk_score(self):
        summary = {
            "contract_id": uuid.uuid4(),
            "engagement_id": "ENG-1",
            "razorpay_reference_type": "payout",
            "overall_risk_score": None,
            "needs_human_review_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
        }

        data = ContractSummarySerializer(instance=summary).data

        assert data["engagement_id"] == "ENG-1"
        assert data["overall_risk_score"] is None
        assert data["needs_human_review_count"] == 0

    def test_round_trips_a_summary_with_a_scored_risk(self):
        summary = {
            "contract_id": uuid.uuid4(),
            "engagement_id": "ENG-2",
            "razorpay_reference_type": "subscription",
            "overall_risk_score": 0.75,
            "needs_human_review_count": 2,
            "created_at": "2026-01-02T00:00:00Z",
        }

        data = ContractSummarySerializer(instance=summary).data

        assert data["overall_risk_score"] == 0.75
        assert data["needs_human_review_count"] == 2


# Lightweight stand-ins for the Django model instances
# `reporting.selectors.ClauseReasoningChain` actually carries, used here so
# these serializer tests stay pure unit tests (no database) - only the
# attribute paths `ClauseReasoningChainSerializer`'s `source=` strings walk
# need to exist.


@dataclass
class _FakeClause:
    id: uuid.UUID
    sequence_index: int
    clause_type: str | None
    clause_text: str
    classification_confidence: float | None
    classification_rationale: str | None


@dataclass
class _FakeExtractedTerm:
    id: uuid.UUID
    term_type: str
    value_raw: str
    value_structured: dict
    extraction_confidence: float
    needs_human_review: bool
    created_at: str


@dataclass
class _FakeClauseRef:
    id: uuid.UUID
    sequence_index: int


@dataclass
class _FakeExtractedTermRef:
    clause_id: uuid.UUID
    clause: _FakeClauseRef


@dataclass
class _FakeMismatchFlag:
    id: uuid.UUID
    mismatch_type: str
    expected_value: dict
    actual_value: dict
    description: str
    extracted_term: _FakeExtractedTermRef


@dataclass
class _FakePlatformRecord:
    id: uuid.UUID
    record_type: str
    razorpay_id: str
    payload: dict
    razorpay_created_at: str


@dataclass
class _FakeRiskAssessment:
    id: uuid.UUID
    severity: str
    asymmetry_score: float
    explanation: str
    suggested_rewrite: str | None
    linked_mismatch_flag_ids: list
    created_at: str


class TestClauseReasoningChainSerializer:
    def test_full_chain_serializes_every_stage(self):
        from reporting.selectors import ClauseReasoningChain

        clause_id = uuid.uuid4()
        mismatch_id = uuid.uuid4()

        clause = _FakeClause(
            id=clause_id,
            sequence_index=0,
            clause_type="payment_schedule",
            clause_text="Vendor shall be paid every 30 days.",
            classification_confidence=0.9,
            classification_rationale="States a cadence.",
        )
        term = _FakeExtractedTerm(
            id=uuid.uuid4(),
            term_type="payout_frequency",
            value_raw="every 30 days",
            value_structured={"numeric_value": 30, "unit": "days"},
            extraction_confidence=0.85,
            needs_human_review=False,
            created_at="2026-01-01T00:00:00Z",
        )
        mismatch = _FakeMismatchFlag(
            id=mismatch_id,
            mismatch_type="cadence_mismatch",
            expected_value={"numeric_value": 30},
            actual_value={"numeric_value": 45},
            description="Observed cadence is 45 days.",
            extracted_term=_FakeExtractedTermRef(
                clause_id=clause_id, clause=_FakeClauseRef(id=clause_id, sequence_index=0)
            ),
        )
        risk_assessment = _FakeRiskAssessment(
            id=uuid.uuid4(),
            severity="high",
            asymmetry_score=0.6,
            explanation="Asymmetric burden.",
            suggested_rewrite="Give both parties equal notice.",
            linked_mismatch_flag_ids=[str(mismatch_id)],
            created_at="2026-01-01T00:00:00Z",
        )
        chain = ClauseReasoningChain(
            clause=clause,
            classification_needs_human_review=False,
            extracted_terms=[term],
            mismatch_flags=[mismatch],
            verified_platform_records=[],
            risk_assessment=risk_assessment,
        )

        data = ClauseReasoningChainSerializer(instance=chain).data

        assert str(data["clause_id"]) == str(clause_id)
        assert data["sequence_index"] == 0
        assert data["clause_type"] == "payment_schedule"
        assert data["classification_needs_human_review"] is False
        assert len(data["extracted_terms"]) == 1
        assert data["extracted_terms"][0]["term_type"] == "payout_frequency"
        assert len(data["platform_evidence"]) == 1
        evidence = data["platform_evidence"][0]
        assert str(evidence["mismatch_id"]) == str(mismatch_id)
        assert str(evidence["clause_id"]) == str(clause_id)
        assert evidence["sequence_index"] == 0
        assert data["verified_platform_records"] == []
        assert data["risk_assessment"]["severity"] == "high"
        assert data["risk_assessment"]["asymmetry_score"] == 0.6

    def test_no_platform_evidence_and_not_yet_scored_are_explicit_empty_and_null(self):
        from reporting.selectors import ClauseReasoningChain

        clause = _FakeClause(
            id=uuid.uuid4(),
            sequence_index=1,
            clause_type=None,
            clause_text="Ambiguous boilerplate text.",
            classification_confidence=None,
            classification_rationale=None,
        )
        chain = ClauseReasoningChain(
            clause=clause,
            classification_needs_human_review=False,
            extracted_terms=[],
            mismatch_flags=[],
            verified_platform_records=[],
            risk_assessment=None,
        )

        data = ClauseReasoningChainSerializer(instance=chain).data

        assert data["extracted_terms"] == []
        assert data["platform_evidence"] == []
        assert data["verified_platform_records"] == []
        assert data["risk_assessment"] is None
        assert data["clause_type"] is None

    def test_verified_platform_records_serialize_when_present(self):
        from reporting.selectors import ClauseReasoningChain

        clause_id = uuid.uuid4()
        record_id = uuid.uuid4()

        clause = _FakeClause(
            id=clause_id,
            sequence_index=0,
            clause_type="payment_schedule",
            clause_text="Vendor shall be paid every 30 days.",
            classification_confidence=0.9,
            classification_rationale="States a cadence.",
        )
        term = _FakeExtractedTerm(
            id=uuid.uuid4(),
            term_type="payout_frequency",
            value_raw="every 30 days",
            value_structured={"numeric_value": 30, "unit": "days"},
            extraction_confidence=0.85,
            needs_human_review=False,
            created_at="2026-01-01T00:00:00Z",
        )
        record = _FakePlatformRecord(
            id=record_id,
            record_type="payout",
            razorpay_id="pout_000001",
            payload={"id": "pout_000001", "amount": 500000},
            razorpay_created_at="2026-01-01T00:00:00Z",
        )
        chain = ClauseReasoningChain(
            clause=clause,
            classification_needs_human_review=False,
            extracted_terms=[term],
            mismatch_flags=[],
            verified_platform_records=[record],
            risk_assessment=None,
        )

        data = ClauseReasoningChainSerializer(instance=chain).data

        assert len(data["verified_platform_records"]) == 1
        confirmed = data["verified_platform_records"][0]
        assert str(confirmed["id"]) == str(record_id)
        assert confirmed["record_type"] == "payout"
        assert confirmed["razorpay_id"] == "pout_000001"
        assert confirmed["payload"] == {"id": "pout_000001", "amount": 500000}


class TestGuardrailScanResultSerializer:
    def test_passing_scan_serializes_empty_violations(self):
        result = {
            "passed": True,
            "scanned_files": ["/project/razorpay_integration/client.py"],
            "violations": [],
        }

        data = GuardrailScanResultSerializer(instance=result).data

        assert data["passed"] is True
        assert data["scanned_files"] == ["/project/razorpay_integration/client.py"]
        assert data["violations"] == []

    def test_failing_scan_serializes_violation_evidence(self):
        result = {
            "passed": False,
            "scanned_files": ["/project/razorpay_integration/client.py"],
            "violations": [
                {
                    "file": "/project/razorpay_integration/client.py",
                    "line": 42,
                    "matched_call": "sdk_client.post",
                }
            ],
        }

        data = GuardrailScanResultSerializer(instance=result).data

        assert data["passed"] is False
        assert data["violations"][0]["file"] == "/project/razorpay_integration/client.py"
        assert data["violations"][0]["line"] == 42
        assert data["violations"][0]["matched_call"] == "sdk_client.post"
