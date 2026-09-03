"""Tests for risk_scoring.selectors (tasks 2.1, 5.3)."""

from __future__ import annotations

import pytest

from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.tests.factories import ExtractedTermFactory
from razorpay_integration.tests.factories import MismatchFlagFactory
from risk_scoring.selectors import (
    get_linked_mismatch_flags,
    get_risk_assessment_for_clause,
    list_risk_assessments_for_contract,
)
from risk_scoring.tests.factories import RiskAssessmentFactory

pytestmark = pytest.mark.django_db


class TestGetLinkedMismatchFlags:
    def test_returns_mismatches_from_two_different_extracted_terms_on_the_same_clause(self):
        clause = ClauseFactory()
        term_a = ExtractedTermFactory(clause=clause)
        term_b = ExtractedTermFactory(clause=clause)
        flag_a = MismatchFlagFactory(extracted_term=term_a)
        flag_b = MismatchFlagFactory(extracted_term=term_b)

        flags = list(get_linked_mismatch_flags(clause=clause))

        assert {f.id for f in flags} == {flag_a.id, flag_b.id}

    def test_excludes_mismatches_on_other_clauses(self):
        clause = ClauseFactory()
        other_clause = ClauseFactory()
        term = ExtractedTermFactory(clause=clause)
        other_term = ExtractedTermFactory(clause=other_clause)
        flag = MismatchFlagFactory(extracted_term=term)
        other_flag = MismatchFlagFactory(extracted_term=other_term)

        flags = list(get_linked_mismatch_flags(clause=clause))

        assert flag in flags
        assert other_flag not in flags

    def test_empty_for_clause_with_no_linked_mismatches(self):
        clause = ClauseFactory()

        assert list(get_linked_mismatch_flags(clause=clause)) == []


class TestGetRiskAssessmentForClause:
    def test_returns_none_for_an_unscored_clause(self):
        clause = ClauseFactory()

        assert get_risk_assessment_for_clause(clause=clause) is None

    def test_returns_the_assessment_for_a_scored_clause(self):
        clause = ClauseFactory()
        assessment = RiskAssessmentFactory(clause=clause)

        result = get_risk_assessment_for_clause(clause=clause)

        assert result is not None
        assert result.id == assessment.id


class TestListRiskAssessmentsForContract:
    def test_returns_assessments_for_the_given_contract_only(self):
        contract_a = ContractFactory()
        contract_b = ContractFactory()
        clause_a = ClauseFactory(contract=contract_a)
        clause_b = ClauseFactory(contract=contract_b)
        assessment_a = RiskAssessmentFactory(clause=clause_a)
        assessment_b = RiskAssessmentFactory(clause=clause_b)

        results = list(list_risk_assessments_for_contract(contract=contract_a))

        assert assessment_a in results
        assessment_ids = {a.id for a in results}
        assert assessment_b.id not in assessment_ids

    def test_empty_for_contract_with_no_assessments(self):
        contract = ContractFactory()

        assert list(list_risk_assessments_for_contract(contract=contract)) == []
