"""Tests for reporting.selectors.get_contract_report (tasks 6.2-6.6)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from contracts.models import ClauseType, RazorpayReferenceType
from contracts.tests.factories import ClauseFactory, ContractFactory
from evaluation.tests.factories import EvalLabelFactory
from pipeline.models import TermType
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.models import PlatformRecordType
from razorpay_integration.tests.factories import MismatchFlagFactory, PlatformRecordFactory
from reporting.selectors import (
    get_contract_document,
    get_contract_report,
    get_contract_reasoning_chain,
    list_contract_summaries,
)
from risk_scoring.models import SeverityChoices
from risk_scoring.tests.factories import RiskAssessmentFactory

pytestmark = pytest.mark.django_db


class TestOverallRiskScoreWeightedMean:
    """Task 6.2 / spec: Fixed severity-to-weight mapping."""

    def test_one_critical_and_one_low_yields_0_625(self):
        contract = ContractFactory()
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract), severity=SeverityChoices.CRITICAL
        )
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract), severity=SeverityChoices.LOW
        )

        report = get_contract_report(contract=contract)

        assert report["overall_risk_score"] == 0.625


class TestHumanReviewClausesExcludedFromScore:
    """Tasks 6.3, 6.4 / spec: Human-review clauses excluded from the score."""

    def test_mixed_contract_excludes_needs_human_review_from_score_but_lists_it_separately(
        self,
    ):
        contract = ContractFactory()
        scored_clause = ClauseFactory(contract=contract)
        RiskAssessmentFactory(clause=scored_clause, severity=SeverityChoices.HIGH)
        review_clause = ClauseFactory(contract=contract)
        RiskAssessmentFactory(
            clause=review_clause,
            severity=SeverityChoices.NEEDS_HUMAN_REVIEW,
            asymmetry_score=0.0,
            explanation="needs human review",
        )

        report = get_contract_report(contract=contract)

        assert report["overall_risk_score"] == 0.75
        flagged_clause_ids = {c["clause_id"] for c in report["flagged_clauses"]}
        review_clause_ids = {c["clause_id"] for c in report["needs_human_review_clauses"]}
        assert scored_clause.id in flagged_clause_ids
        assert review_clause.id not in flagged_clause_ids
        assert review_clause.id in review_clause_ids

    def test_all_unreviewed_contract_yields_none_not_zero(self):
        contract = ContractFactory()
        for _ in range(3):
            RiskAssessmentFactory(
                clause=ClauseFactory(contract=contract),
                severity=SeverityChoices.NEEDS_HUMAN_REVIEW,
                asymmetry_score=0.0,
            )

        report = get_contract_report(contract=contract)

        assert report["overall_risk_score"] is None
        assert len(report["needs_human_review_clauses"]) == 3
        assert report["flagged_clauses"] == []

    def test_contract_with_no_risk_assessments_at_all_yields_none(self):
        contract = ContractFactory()

        report = get_contract_report(contract=contract)

        assert report["overall_risk_score"] is None
        assert report["flagged_clauses"] == []
        assert report["needs_human_review_clauses"] == []


class TestMismatchesCombinedIntoReport:
    """Task 6.5 / spec: Mismatches combined into the report."""

    def test_every_mismatch_across_two_clauses_appears_with_its_source_clause(self):
        contract = ContractFactory()
        clause_a = ClauseFactory(contract=contract)
        clause_b = ClauseFactory(contract=contract)
        term_a = ExtractedTermFactory(clause=clause_a)
        term_b = ExtractedTermFactory(clause=clause_b)
        flag_a = MismatchFlagFactory(extracted_term=term_a)
        flag_b = MismatchFlagFactory(extracted_term=term_b)

        report = get_contract_report(contract=contract)

        mismatches_by_id = {m["mismatch_id"]: m for m in report["platform_mismatches"]}
        assert set(mismatches_by_id) == {flag_a.id, flag_b.id}
        assert mismatches_by_id[flag_a.id]["clause_id"] == clause_a.id
        assert mismatches_by_id[flag_b.id]["clause_id"] == clause_b.id

    def test_no_mismatches_for_a_contract_with_none(self):
        contract = ContractFactory()

        report = get_contract_report(contract=contract)

        assert report["platform_mismatches"] == []


class TestRankedByDescendingSeverityThenAsymmetry:
    def test_flagged_clauses_ranked_by_severity_weight_then_abs_asymmetry(self):
        contract = ContractFactory()
        low = RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract),
            severity=SeverityChoices.LOW,
            asymmetry_score=0.1,
        )
        high_small_asym = RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract),
            severity=SeverityChoices.HIGH,
            asymmetry_score=0.6,
        )
        high_large_asym = RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract),
            severity=SeverityChoices.HIGH,
            asymmetry_score=-0.95,
        )
        critical = RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract),
            severity=SeverityChoices.CRITICAL,
            asymmetry_score=0.9,
        )

        report = get_contract_report(contract=contract)

        ranked_ids = [c["clause_id"] for c in report["flagged_clauses"]]
        assert ranked_ids == [
            critical.clause_id,
            high_large_asym.clause_id,
            high_small_asym.clause_id,
            low.clause_id,
        ]


class TestDeterministicLLMFreeAggregation:
    """Task 6.6 / spec: Deterministic, LLM-free aggregation."""

    @patch("core.llm_client.get_structured_completion")
    def test_repeated_calls_agree_and_issue_no_claude_call(self, mock_completion):
        mock_completion.side_effect = AssertionError(
            "get_contract_report must never call the Claude API"
        )
        contract = ContractFactory()
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract), severity=SeverityChoices.HIGH
        )
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract),
            severity=SeverityChoices.NEEDS_HUMAN_REVIEW,
            asymmetry_score=0.0,
        )
        term = ExtractedTermFactory(clause=ClauseFactory(contract=contract))
        MismatchFlagFactory(extracted_term=term)

        first = get_contract_report(contract=contract)
        second = get_contract_report(contract=contract)

        assert first == second
        mock_completion.assert_not_called()


class TestClauseTypeBreakdown:
    """Tasks 1.1-1.3 / spec: reporting/clause-type-breakdown."""

    def test_counts_and_mean_asymmetry_per_clause_type_for_multiple_scored_types(self):
        contract = ContractFactory()
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract, clause_type=ClauseType.TERMINATION),
            severity=SeverityChoices.HIGH,
            asymmetry_score=0.6,
        )
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract, clause_type=ClauseType.TERMINATION),
            severity=SeverityChoices.MEDIUM,
            asymmetry_score=0.4,
        )
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract, clause_type=ClauseType.INDEMNITY),
            severity=SeverityChoices.CRITICAL,
            asymmetry_score=0.9,
        )

        report = get_contract_report(contract=contract)

        breakdown = report["severity_breakdown_by_clause_type"]
        assert set(breakdown) == {"termination", "indemnity"}
        assert breakdown["termination"] == {"count": 2, "mean_asymmetry_score": 0.5}
        assert breakdown["indemnity"] == {"count": 1, "mean_asymmetry_score": 0.9}

    def test_no_scored_clauses_yields_empty_breakdown_not_omitted_or_error(self):
        contract = ContractFactory()

        report = get_contract_report(contract=contract)

        assert report["severity_breakdown_by_clause_type"] == {}

    def test_needs_human_review_clause_never_contributes_to_any_group(self):
        contract = ContractFactory()
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract, clause_type=ClauseType.TERMINATION),
            severity=SeverityChoices.HIGH,
            asymmetry_score=0.6,
        )
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract, clause_type=ClauseType.TERMINATION),
            severity=SeverityChoices.NEEDS_HUMAN_REVIEW,
            asymmetry_score=0.0,
        )

        report = get_contract_report(contract=contract)

        breakdown = report["severity_breakdown_by_clause_type"]
        assert breakdown["termination"] == {"count": 1, "mean_asymmetry_score": 0.6}


class TestListContractSummaries:
    """Task 3.1 / spec: api/contract-listing - Summary reflects current pipeline state."""

    def test_overall_risk_score_is_null_for_a_contract_with_no_scored_clauses(self):
        contract = ContractFactory()
        ClauseFactory(contract=contract)

        summaries = list_contract_summaries()

        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.contract_id == contract.id
        assert summary.overall_risk_score is None
        assert summary.needs_human_review_count == 0

    def test_summary_fields_match_the_contract_and_its_aggregate_report(self):
        contract = ContractFactory()
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract), severity=SeverityChoices.HIGH
        )
        RiskAssessmentFactory(
            clause=ClauseFactory(contract=contract),
            severity=SeverityChoices.NEEDS_HUMAN_REVIEW,
            asymmetry_score=0.0,
        )

        summaries = list_contract_summaries()

        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.contract_id == contract.id
        assert summary.engagement_id == contract.engagement_id
        assert summary.razorpay_reference_type == contract.razorpay_reference_type
        assert summary.overall_risk_score == 0.75
        assert summary.needs_human_review_count == 1
        assert summary.created_at == contract.created_at

    def test_empty_project_yields_empty_list(self):
        assert list_contract_summaries() == []

    def test_summaries_ordered_newest_contract_first(self):
        first = ContractFactory()
        second = ContractFactory()

        summaries = list_contract_summaries()

        assert [s.contract_id for s in summaries] == [second.id, first.id]

    def test_excludes_synthetic_evaluation_fixture_contracts(self):
        """A Contract with an EvalLabel is an eval-dataset fixture, not a
        real ingested contract - see evaluation.selectors.
        list_eval_fixture_contract_ids. It must never appear in the
        user-facing contract list, including one left "not yet classified"
        by a dataset-generation run that was interrupted partway through
        (e.g. by an OpenAI rate limit)."""
        real_contract = ContractFactory()
        fixture_contract = ContractFactory(engagement_id="synthetic-v1-001")
        EvalLabelFactory(contract=fixture_contract, clause=ClauseFactory(contract=fixture_contract))

        summaries = list_contract_summaries()

        assert [s.contract_id for s in summaries] == [real_contract.id]


class TestVerifiedPlatformRecordsOnReasoningChain:
    """Task 1.1 / spec: reporting/confirmed-platform-evidence."""

    def test_matching_contract_shows_confirmed_evidence(self):
        """Spec scenario: Matching contract shows confirmed evidence."""
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract, sequence_index=0)
        ExtractedTermFactory(clause=clause)
        payout_record = PlatformRecordFactory(
            contract=contract, record_type=PlatformRecordType.PAYOUT
        )

        chains = get_contract_reasoning_chain(contract=contract)

        assert len(chains) == 1
        assert [r.id for r in chains[0].verified_platform_records] == [payout_record.id]

    def test_subscription_referenced_contract_gets_both_subscription_and_token_records(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        clause = ClauseFactory(contract=contract, sequence_index=0)
        ExtractedTermFactory(clause=clause)
        subscription_record = PlatformRecordFactory(
            contract=contract, record_type=PlatformRecordType.SUBSCRIPTION
        )
        token_record = PlatformRecordFactory(
            contract=contract, record_type=PlatformRecordType.TOKEN
        )
        # A payout record on the same contract should never leak in - not
        # relevant to a subscription-referenced contract.
        PlatformRecordFactory(contract=contract, record_type=PlatformRecordType.PAYOUT)

        chains = get_contract_reasoning_chain(contract=contract)

        record_ids = {r.id for r in chains[0].verified_platform_records}
        assert record_ids == {subscription_record.id, token_record.id}

    def test_no_platform_data_ever_checked_stays_empty(self):
        """Spec scenario: No platform data ever checked."""
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract, sequence_index=0)
        ExtractedTermFactory(clause=clause)

        chains = get_contract_reasoning_chain(contract=contract)

        assert chains[0].verified_platform_records == []

    def test_mismatched_clause_does_not_also_show_confirmed_evidence(self):
        """Spec scenario: Mismatched clause does not also show confirmed evidence."""
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract, sequence_index=0)
        term = ExtractedTermFactory(clause=clause)
        MismatchFlagFactory(extracted_term=term)
        PlatformRecordFactory(contract=contract, record_type=PlatformRecordType.PAYOUT)

        chains = get_contract_reasoning_chain(contract=contract)

        assert chains[0].mismatch_flags != []
        assert chains[0].verified_platform_records == []

    def test_clause_with_no_extracted_terms_stays_empty_even_with_platform_data(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        ClauseFactory(contract=contract, sequence_index=0)
        PlatformRecordFactory(contract=contract, record_type=PlatformRecordType.PAYOUT)

        chains = get_contract_reasoning_chain(contract=contract)

        assert chains[0].extracted_terms == []
        assert chains[0].verified_platform_records == []


class TestOverdueStatusesOnReasoningChain:
    """Spec: razorpay-integration/overdue-payment-detection - "Overdue status
    is surfaced on the reasoning-chain API at clause grain"."""

    @override_settings(CADENCE_MISMATCH_TOLERANCE_RATIO=0.2)
    def test_clause_with_an_overdue_term_surfaces_it(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract, sequence_index=0)
        term = ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_structured={"numeric_value": 30, "unit": "days"},
        )
        PlatformRecordFactory(
            contract=contract,
            record_type=PlatformRecordType.PAYOUT,
            razorpay_created_at=timezone.now() - timedelta(days=40),
        )

        chains = get_contract_reasoning_chain(contract=contract)

        assert len(chains) == 1
        statuses = chains[0].overdue_statuses
        assert len(statuses) == 1
        assert statuses[0].term_id == term.id
        assert statuses[0].is_overdue is True

    def test_clause_with_no_qualifying_term_has_an_empty_list(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        ClauseFactory(contract=contract, sequence_index=0)

        chains = get_contract_reasoning_chain(contract=contract)

        assert chains[0].overdue_statuses == []

    def test_overdue_status_is_attributed_to_the_owning_clause_only(self):
        """A Contract with two payment-schedule clauses - the overdue
        status for one clause's term must never leak onto the other."""
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause_a = ClauseFactory(contract=contract, sequence_index=0)
        clause_b = ClauseFactory(contract=contract, sequence_index=1)
        term_a = ExtractedTermFactory(
            clause=clause_a,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_structured={"numeric_value": 30, "unit": "days"},
        )
        PlatformRecordFactory(
            contract=contract,
            record_type=PlatformRecordType.PAYOUT,
            razorpay_created_at=timezone.now() - timedelta(days=5),
        )

        chains = get_contract_reasoning_chain(contract=contract)

        chain_by_clause_id = {chain.clause.id: chain for chain in chains}
        assert len(chain_by_clause_id[clause_a.id].overdue_statuses) == 1
        assert chain_by_clause_id[clause_a.id].overdue_statuses[0].term_id == term_a.id
        assert chain_by_clause_id[clause_b.id].overdue_statuses == []

    def test_amount_type_term_never_surfaces_an_overdue_status(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.PAYOUT)
        clause = ClauseFactory(contract=contract, sequence_index=0)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_structured={"numeric_value": 500, "unit": "INR"},
        )
        PlatformRecordFactory(
            contract=contract,
            record_type=PlatformRecordType.PAYOUT,
            razorpay_created_at=timezone.now() - timedelta(days=400),
        )

        chains = get_contract_reasoning_chain(contract=contract)

        assert chains[0].overdue_statuses == []

    def test_subscription_referenced_contract_never_surfaces_an_overdue_status(self):
        contract = ContractFactory(razorpay_reference_type=RazorpayReferenceType.SUBSCRIPTION)
        clause = ClauseFactory(contract=contract, sequence_index=0)
        ExtractedTermFactory(
            clause=clause,
            term_type=TermType.PAYOUT_FREQUENCY,
            value_structured={"numeric_value": 30, "unit": "days"},
        )

        chains = get_contract_reasoning_chain(contract=contract)

        assert chains[0].overdue_statuses == []


class TestContractDocumentNeedsHumanReview:
    """Contract-level needs_human_review/human_review_reason surfaced on
    ContractDocument - set by contracts.services.mark_contract_needs_human_review
    when stage-1 segmentation fails verbatim-matching twice, previously set
    on the model but never read back out through any selector."""

    def test_flagged_contract_carries_its_review_flag_and_reason(self):
        contract = ContractFactory(
            needs_human_review=True,
            human_review_reason="Stage-1 segmentation failed verbatim-matching twice.",
        )

        document = get_contract_document(contract=contract)

        assert document.needs_human_review is True
        assert document.human_review_reason == "Stage-1 segmentation failed verbatim-matching twice."

    def test_unflagged_contract_defaults_to_false_and_no_reason(self):
        contract = ContractFactory()

        document = get_contract_document(contract=contract)

        assert document.needs_human_review is False
        assert document.human_review_reason is None
