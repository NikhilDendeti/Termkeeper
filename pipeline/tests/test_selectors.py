"""Tests for pipeline.selectors.

Spec: specs/pipeline/audit-trail/spec.md (Audit trail queryable per
contract) and specs/pipeline/term-extraction/spec.md (Extracted term
traceable to its clause).
"""

import pytest

from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.models import PipelineStage
from pipeline.selectors import get_audit_trail, list_extracted_terms_for_clause
from pipeline.tests.factories import AuditLogEntryFactory, ExtractedTermFactory

pytestmark = pytest.mark.django_db


class TestGetAuditTrail:
    """Requirement: Audit trail queryable per contract."""

    def test_full_trail_retrievable_ordered_by_stage_then_created_at(self):
        # Scenario: Full trail retrievable
        contract = ContractFactory()

        # Deliberately created out of stage order to prove the ordering
        # isn't accidental (e.g. isn't just insertion/PK order).
        entry_stage3 = AuditLogEntryFactory(
            contract=contract, stage=PipelineStage.EXTRACTION, prompt_version="term-extraction-v1"
        )
        entry_stage1_first = AuditLogEntryFactory(
            contract=contract,
            stage=PipelineStage.SEGMENTATION,
            prompt_version="clause-segmentation-v1",
        )
        entry_stage2 = AuditLogEntryFactory(
            contract=contract,
            stage=PipelineStage.CLASSIFICATION,
            prompt_version="clause-classification-v1",
        )
        entry_stage1_second = AuditLogEntryFactory(
            contract=contract,
            stage=PipelineStage.SEGMENTATION,
            prompt_version="clause-segmentation-v1-retry",
        )

        trail = list(get_audit_trail(contract=contract))

        assert [entry.id for entry in trail] == [
            entry_stage1_first.id,
            entry_stage1_second.id,
            entry_stage2.id,
            entry_stage3.id,
        ]
        assert [entry.stage for entry in trail] == [1, 1, 2, 3]

    def test_only_returns_entries_for_the_given_contract(self):
        contract_a = ContractFactory()
        contract_b = ContractFactory()
        AuditLogEntryFactory(contract=contract_a, stage=PipelineStage.SEGMENTATION)
        other_entry = AuditLogEntryFactory(contract=contract_b, stage=PipelineStage.SEGMENTATION)

        trail = list(get_audit_trail(contract=contract_a))

        assert other_entry not in trail
        assert all(entry.contract_id == contract_a.id for entry in trail)

    def test_empty_for_contract_with_no_audit_entries(self):
        contract = ContractFactory()

        assert list(get_audit_trail(contract=contract)) == []


class TestListExtractedTermsForClause:
    def test_returns_terms_for_the_given_clause_only(self):
        clause_a = ClauseFactory()
        clause_b = ClauseFactory()
        term_a = ExtractedTermFactory(clause=clause_a)
        other_term = ExtractedTermFactory(clause=clause_b)

        terms = list(list_extracted_terms_for_clause(clause=clause_a))

        assert term_a in terms
        assert other_term not in terms
        assert all(term.clause_id == clause_a.id for term in terms)

    def test_empty_for_clause_with_no_extracted_terms(self):
        clause = ClauseFactory()

        assert list(list_extracted_terms_for_clause(clause=clause)) == []
