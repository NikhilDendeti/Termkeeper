"""Tests for pipeline.services.segment_contract.

Spec: specs/pipeline/clause-segmentation/spec.md. Every
`core.llm_client.get_structured_completion` call is mocked - no real
network call is made.
"""

from unittest.mock import patch

import pytest

from contracts.models import Clause, Contract
from contracts.tests.factories import ContractFactory
from pipeline.models import AuditLogEntry
from pipeline.services import segment_contract

pytestmark = pytest.mark.django_db

CLAUSE_1_TEXT = (
    "1. Payment Terms. Vendor shall invoice Client monthly. Payment is due "
    "net 30 days from the invoice date."
)
CLAUSE_2_TEXT = (
    "2. Termination. Either party may terminate this Agreement upon 30 "
    "days written notice."
)
TWO_CLAUSE_CONTRACT_TEXT = f"{CLAUSE_1_TEXT}\n\n{CLAUSE_2_TEXT}"

MULTI_TOPIC_CLAUSE_TEXT = (
    "3. Confidentiality. Each party shall protect the other's confidential "
    "information as follows:\n"
    "(a) using it only for purposes of this Agreement;\n"
    "(b) not disclosing it to third parties without consent;\n"
    "(c) returning or destroying it upon termination of this Agreement."
)

TABLE_LINEBREAK_SOURCE = (
    "Payment Milestones. Description Trigger % of Total\nAmount\n(INR)\n"
    "1. Kickoff — Planning & Design On signing & engagement kickoff 25% ₹2,50,000"
)
TABLE_LINEBREAK_PROPOSED_CLAUSE = (
    "(INR) 1. Kickoff — Planning & Design On signing & engagement kickoff 25% ₹2,50,000"
)


def _segmentation_response(*texts: str) -> dict:
    return {"clauses": [{"text": text} for text in texts]}


class TestVerbatimClauseExtraction:
    """Requirement: Verbatim clause extraction."""

    @patch("core.llm_client.get_structured_completion")
    def test_every_clause_text_found_verbatim_in_source(self, mock_completion):
        # Scenario: Clause text matches source exactly
        contract = ContractFactory(raw_text=TWO_CLAUSE_CONTRACT_TEXT)
        mock_completion.return_value = _segmentation_response(CLAUSE_1_TEXT, CLAUSE_2_TEXT)

        clauses = segment_contract(contract=contract)

        assert len(clauses) == 2
        for clause in clauses:
            assert clause.clause_text in contract.raw_text

    @patch("core.llm_client.get_structured_completion")
    def test_clauses_persisted_with_correct_text_and_sequence(self, mock_completion):
        contract = ContractFactory(raw_text=TWO_CLAUSE_CONTRACT_TEXT)
        mock_completion.return_value = _segmentation_response(CLAUSE_1_TEXT, CLAUSE_2_TEXT)

        clauses = segment_contract(contract=contract)

        assert [c.clause_text for c in clauses] == [CLAUSE_1_TEXT, CLAUSE_2_TEXT]
        assert [c.sequence_index for c in clauses] == [0, 1]
        assert Clause.objects.filter(contract=contract).count() == 2

    @patch("core.llm_client.get_structured_completion")
    def test_table_extraction_linebreak_does_not_block_verbatim_match(self, mock_completion):
        """A table-cell line break in raw_text, collapsed to a space by the model, must not
        cause a false escalation to needs_human_review (regression case for a real production
        document)."""
        contract = ContractFactory(raw_text=TABLE_LINEBREAK_SOURCE)
        mock_completion.return_value = _segmentation_response(TABLE_LINEBREAK_PROPOSED_CLAUSE)

        clauses = segment_contract(contract=contract)

        assert mock_completion.call_count == 1  # succeeds on first attempt, no retry needed
        assert len(clauses) == 1
        assert clauses[0].clause_text == TABLE_LINEBREAK_PROPOSED_CLAUSE
        reloaded = Contract.objects.get(id=contract.id)
        assert reloaded.needs_human_review is False


class TestMultiTopicClausesStayWhole:
    """Requirement: Multi-topic clauses stay whole."""

    @patch("core.llm_client.get_structured_completion")
    def test_clause_with_sub_bullets_segmented_as_one_unit(self, mock_completion):
        # Scenario: Clause with sub-bullets segmented as one unit
        contract = ContractFactory(raw_text=MULTI_TOPIC_CLAUSE_TEXT)
        mock_completion.return_value = _segmentation_response(MULTI_TOPIC_CLAUSE_TEXT)

        clauses = segment_contract(contract=contract)

        assert len(clauses) == 1
        assert clauses[0].clause_text == MULTI_TOPIC_CLAUSE_TEXT
        assert "(a)" in clauses[0].clause_text
        assert "(b)" in clauses[0].clause_text
        assert "(c)" in clauses[0].clause_text


class TestSegmentationFailureEscalated:
    """Requirement: Segmentation failure is escalated, not silently repaired."""

    @patch("core.llm_client.get_structured_completion")
    def test_non_verbatim_output_after_retry_marks_needs_human_review(self, mock_completion):
        # Scenario: Non-verbatim output after retry
        contract = ContractFactory(raw_text=TWO_CLAUSE_CONTRACT_TEXT)
        non_verbatim_response = _segmentation_response(
            "This is a paraphrased clause that does not appear in the source."
        )
        mock_completion.side_effect = [non_verbatim_response, non_verbatim_response]

        result = segment_contract(contract=contract)

        assert result == []
        assert mock_completion.call_count == 2

        reloaded = Contract.objects.get(id=contract.id)
        assert reloaded.needs_human_review is True
        assert reloaded.human_review_reason

        assert Clause.objects.filter(contract=contract).count() == 0

    @patch("core.llm_client.get_structured_completion")
    def test_recovers_if_retry_produces_verbatim_output(self, mock_completion):
        """A first-attempt failure that is fixed on retry should still succeed."""
        contract = ContractFactory(raw_text=TWO_CLAUSE_CONTRACT_TEXT)
        bad_response = _segmentation_response("Not present in the source text at all.")
        good_response = _segmentation_response(CLAUSE_1_TEXT, CLAUSE_2_TEXT)
        mock_completion.side_effect = [bad_response, good_response]

        clauses = segment_contract(contract=contract)

        assert mock_completion.call_count == 2
        assert len(clauses) == 2
        reloaded = Contract.objects.get(id=contract.id)
        assert reloaded.needs_human_review is False


class TestClauseOrderingPreserved:
    """Requirement: Clause ordering preserved."""

    @patch("core.llm_client.get_structured_completion")
    def test_clauses_retrievable_in_source_order(self, mock_completion):
        # Scenario: Clauses retrievable in source order
        contract = ContractFactory(raw_text=TWO_CLAUSE_CONTRACT_TEXT)
        mock_completion.return_value = _segmentation_response(CLAUSE_1_TEXT, CLAUSE_2_TEXT)

        segment_contract(contract=contract)

        ordered = list(Clause.objects.filter(contract=contract).order_by("sequence_index"))
        assert [c.clause_text for c in ordered] == [CLAUSE_1_TEXT, CLAUSE_2_TEXT]


class TestSegmentationAuditLogEntry:
    """One AuditLogEntry (stage=1) per segment_contract call."""

    @patch("core.llm_client.get_structured_completion")
    def test_one_audit_log_entry_created_on_success(self, mock_completion):
        contract = ContractFactory(raw_text=TWO_CLAUSE_CONTRACT_TEXT)
        mock_completion.return_value = _segmentation_response(CLAUSE_1_TEXT, CLAUSE_2_TEXT)

        segment_contract(contract=contract)

        entries = AuditLogEntry.objects.filter(contract=contract, stage=1)
        assert entries.count() == 1
        entry = entries.get()
        assert entry.clause is None
        assert entry.prompt_version == "clause-segmentation-v1"
        assert entry.llm_response_raw == _segmentation_response(CLAUSE_1_TEXT, CLAUSE_2_TEXT)

    @patch("core.llm_client.get_structured_completion")
    def test_exactly_one_audit_log_entry_even_after_a_retry(self, mock_completion):
        contract = ContractFactory(raw_text=TWO_CLAUSE_CONTRACT_TEXT)
        bad_response = _segmentation_response("Not present in the source text at all.")
        good_response = _segmentation_response(CLAUSE_1_TEXT, CLAUSE_2_TEXT)
        mock_completion.side_effect = [bad_response, good_response]

        segment_contract(contract=contract)

        assert AuditLogEntry.objects.filter(contract=contract, stage=1).count() == 1
