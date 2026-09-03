"""Tests for report_ui.views.contract_report_view (tasks 2.1-2.8).

Spec: report-ui/reasoning-chain-view.
"""

from __future__ import annotations

import uuid

import pytest
from django.urls import reverse

from contracts.models import ClauseType
from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.models import TermType
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.tests.factories import MismatchFlagFactory, PlatformRecordFactory
from risk_scoring.models import SeverityChoices
from risk_scoring.tests.factories import RiskAssessmentFactory

pytestmark = pytest.mark.django_db


def _report_url(contract_id) -> str:
    return reverse("contract_report", kwargs={"contract_id": contract_id})


class TestContractReportViewBasics:
    """Task 2.1."""

    def test_returns_200_for_contract_with_at_least_one_clause(self, client):
        contract = ContractFactory()
        ClauseFactory(contract=contract, sequence_index=0)

        response = client.get(_report_url(contract.id))

        assert response.status_code == 200

    def test_unknown_contract_id_returns_404(self, client):
        response = client.get(_report_url(uuid.uuid4()))

        assert response.status_code == 404


class TestClauseOrder:
    """Task 2.2 / spec: Clauses listed in sequence order."""

    def test_clauses_render_in_ascending_sequence_index_order(self, client):
        contract = ContractFactory()
        ClauseFactory(contract=contract, sequence_index=2, clause_text="Clause C body")
        ClauseFactory(contract=contract, sequence_index=0, clause_text="Clause A body")
        ClauseFactory(contract=contract, sequence_index=1, clause_text="Clause B body")

        response = client.get(_report_url(contract.id))
        content = response.content.decode()

        index_a = content.index("Clause A body")
        index_b = content.index("Clause B body")
        index_c = content.index("Clause C body")
        assert index_a < index_b < index_c


class TestFullReasoningChain:
    """Task 2.3 / spec: Full reasoning chain shown per clause."""

    def test_all_five_stages_appear_in_order_for_a_fully_processed_clause(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(
            contract=contract,
            sequence_index=0,
            clause_text="Vendor shall be paid every 30 days from invoice date.",
            clause_type=ClauseType.PAYMENT_SCHEDULE,
            classification_confidence=0.91,
            classification_rationale="Clause states a recurring payout cadence.",
        )
        term = ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_raw="paid every 30 days from invoice date",
            value_structured={"numeric_value": 30, "unit": "days"},
            extraction_confidence=0.88,
        )
        MismatchFlagFactory(
            extracted_term=term,
            description="Observed payout cadence is 45 days, not 30.",
        )
        RiskAssessmentFactory(
            clause=clause,
            severity=SeverityChoices.HIGH,
            explanation="This clause imposes an asymmetric payment burden.",
        )

        response = client.get(_report_url(contract.id))
        content = response.content.decode()

        assert "Vendor shall be paid every 30 days from invoice date." in content
        assert "Payment schedule" in content
        assert "paid every 30 days from invoice date" in content
        assert "Observed payout cadence is 45 days, not 30." in content
        assert "This clause imposes an asymmetric payment burden." in content

        # Order: clause text -> classification -> extraction -> platform evidence -> risk verdict.
        idx_clause_text = content.index("Clause text")
        idx_classification = content.index("Classification")
        idx_extraction = content.index("Extracted term(s)")
        idx_platform = content.index("Platform evidence")
        idx_risk = content.index("Risk verdict")
        assert idx_clause_text < idx_classification < idx_extraction < idx_platform < idx_risk


class TestNoPlatformEvidence:
    """Task 2.4 / spec: Clause with no platform evidence."""

    def test_renders_explicit_no_platform_evidence_message(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(
            contract=contract, sequence_index=0, clause_type=ClauseType.PAYMENT_SCHEDULE
        )
        ExtractedTermFactory(clause=clause, term_type=TermType.PAYOUT_FREQUENCY)

        response = client.get(_report_url(contract.id))

        assert "no platform evidence available" in response.content.decode()


class TestConfirmedPlatformEvidence:
    """Task 2.1 (add-confirmed-platform-evidence) / spec:
    reporting/confirmed-platform-evidence.

    See openspec/changes/add-confirmed-platform-evidence/specs/reporting/
    confirmed-platform-evidence/spec.md.
    """

    def test_confirmed_block_renders_for_clause_with_verified_platform_records(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(
            contract=contract, sequence_index=0, clause_type=ClauseType.PAYMENT_SCHEDULE
        )
        ExtractedTermFactory(clause=clause, term_type=TermType.PAYOUT_FREQUENCY)
        PlatformRecordFactory(contract=contract, razorpay_id="pout_000001")

        response = client.get(_report_url(contract.id))
        content = response.content.decode()

        assert "Confirmed - matches platform data" in content
        assert "pout_000001" in content
        assert "no platform evidence available" not in content

    def test_confirmed_block_does_not_render_for_clause_without_platform_records(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(
            contract=contract, sequence_index=0, clause_type=ClauseType.PAYMENT_SCHEDULE
        )
        ExtractedTermFactory(clause=clause, term_type=TermType.PAYOUT_FREQUENCY)

        response = client.get(_report_url(contract.id))
        content = response.content.decode()

        assert "Confirmed - matches platform data" not in content
        assert "no platform evidence available" in content

    def test_mismatch_takes_precedence_over_confirmed_evidence(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(
            contract=contract, sequence_index=0, clause_type=ClauseType.PAYMENT_SCHEDULE
        )
        term = ExtractedTermFactory(clause=clause, term_type=TermType.PAYOUT_FREQUENCY)
        platform_record = PlatformRecordFactory(contract=contract, razorpay_id="pout_000002")
        MismatchFlagFactory(
            extracted_term=term,
            platform_record=platform_record,
            description="Observed payout cadence is 45 days, not 30.",
        )

        response = client.get(_report_url(contract.id))
        content = response.content.decode()

        assert "Observed payout cadence is 45 days, not 30." in content
        assert "Confirmed - matches platform data" not in content


class TestNotYetRiskScored:
    """Task 2.5 / spec: Clause not yet risk-scored."""

    def test_renders_explicit_not_yet_assessed_message(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(
            contract=contract, sequence_index=0, clause_type=ClauseType.PAYMENT_SCHEDULE
        )
        ExtractedTermFactory(clause=clause, term_type=TermType.PAYOUT_FREQUENCY)

        response = client.get(_report_url(contract.id))

        assert "not yet assessed" in response.content.decode()


class TestNeedsHumanReviewDistinctFromSeverity:
    """Task 2.6 / spec: needs_human_review renders distinctly from every scored severity."""

    def test_needs_human_review_item_never_carries_a_severity_class(self, client):
        contract = ContractFactory()
        ClauseFactory(
            contract=contract,
            sequence_index=0,
            clause_type=ClauseType.NEEDS_HUMAN_REVIEW,
            classification_confidence=0.4,
        )

        response = client.get(_report_url(contract.id))
        content = response.content.decode()

        assert 'class="needs-review"' in content
        assert "severity-" not in content


class TestNeedsHumanReviewTextLabel:
    """Task 2.7 / spec: needs-human-review state conveyed by text label, not color alone."""

    def test_label_text_present_in_response_content(self, client):
        contract = ContractFactory()
        ClauseFactory(
            contract=contract, sequence_index=0, clause_type=ClauseType.NEEDS_HUMAN_REVIEW
        )

        response = client.get(_report_url(contract.id))

        assert "Needs human review" in response.content.decode()


class TestNeedsHumanReviewIndependentOfLaterStages:
    """Task 2.8 / spec: Distinct treatment holds independent of later stages."""

    def test_classification_needs_review_treatment_survives_a_differing_later_severity(
        self, client
    ):
        contract = ContractFactory()
        clause = ClauseFactory(
            contract=contract,
            sequence_index=0,
            clause_type=ClauseType.NEEDS_HUMAN_REVIEW,
        )
        # Deliberately give this clause a scored risk verdict distinct from
        # needs_human_review, to prove the classification stage's own
        # treatment does not depend on what severity a later stage carries.
        RiskAssessmentFactory(clause=clause, severity=SeverityChoices.HIGH)

        response = client.get(_report_url(contract.id))
        content = response.content.decode()

        assert "Needs human review" in content
        assert "severity-high" in content
