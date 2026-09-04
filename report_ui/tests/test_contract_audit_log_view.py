"""Tests for report_ui.views.contract_audit_log_view (tasks 3.1-3.5).

Spec: report-ui/audit-log-view.
"""

from __future__ import annotations

import uuid

import pytest
from django.urls import reverse

from contracts.tests.factories import ClauseFactory, ContractFactory
from pipeline.models import AuditLogEntry
from pipeline.services import create_audit_log_entry
from pipeline.tests.factories import AuditLogEntryFactory

pytestmark = pytest.mark.django_db


def _audit_log_url(contract_id) -> str:
    return reverse("contract_audit_log", kwargs={"contract_id": contract_id})


class TestContractAuditLogViewBasics:
    """Task 3.1."""

    def test_returns_200_for_contract_with_audit_entries(self, client):
        contract = ContractFactory()
        AuditLogEntryFactory(contract=contract, stage=1)

        response = client.get(_audit_log_url(contract.id))

        assert response.status_code == 200

    def test_unknown_contract_id_returns_404(self, client):
        response = client.get(_audit_log_url(uuid.uuid4()))

        assert response.status_code == 404


class TestAuditTrailStageOrder:
    """Task 3.2 / spec: Complete audit trail rendered in stage order."""

    def test_entries_across_three_plus_stages_render_in_stage_order(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(contract=contract, sequence_index=0)
        # Insert out of order to prove the page re-orders by stage, not
        # creation order.
        AuditLogEntryFactory(
            contract=contract, clause=clause, stage=3, prompt_version="extraction-v1"
        )
        AuditLogEntryFactory(contract=contract, clause=None, stage=1, prompt_version="segment-v1")
        AuditLogEntryFactory(
            contract=contract, clause=clause, stage=2, prompt_version="classify-v1"
        )

        response = client.get(_audit_log_url(contract.id))
        content = response.content.decode()

        idx_1 = content.index("segment-v1")
        idx_2 = content.index("classify-v1")
        idx_3 = content.index("extraction-v1")
        assert idx_1 < idx_2 < idx_3

    def test_no_entry_is_omitted(self, client):
        contract = ContractFactory()
        for stage in range(1, 6):
            AuditLogEntryFactory(contract=contract, stage=stage, prompt_version=f"stage-{stage}")

        response = client.get(_audit_log_url(contract.id))
        content = response.content.decode()

        for stage in range(1, 6):
            assert f"stage-{stage}" in content


class TestEntryMetadataVisible:
    """Task 3.3 / spec: Entry metadata visible without further navigation."""

    def test_prompt_version_model_name_and_latency_appear_per_entry(self, client):
        contract = ContractFactory()
        AuditLogEntryFactory(
            contract=contract,
            stage=1,
            prompt_version="clause-segmentation-v1",
            model_name="claude-sonnet-5",
            latency_ms=1234,
        )

        response = client.get(_audit_log_url(contract.id))
        content = response.content.decode()

        assert "clause-segmentation-v1" in content
        assert "claude-sonnet-5" in content
        assert "1234" in content


class TestRawResponseInspectable:
    """Task 3.4 / spec: Raw model response inspectable per entry."""

    def test_full_raw_response_present_in_response_content(self, client):
        contract = ContractFactory()
        AuditLogEntryFactory(
            contract=contract,
            stage=1,
            llm_response_raw={"clauses": [{"text": "a distinctive raw payload marker"}]},
        )

        response = client.get(_audit_log_url(contract.id))
        content = response.content.decode()

        assert "a distinctive raw payload marker" in content
        # pretty_json formats with indentation - confirm it was actually
        # run through the filter, not just str()'d. The output is rendered
        # inside a template variable, so quotes are HTML-escaped as usual.
        assert "clauses" in content
        assert "&quot;" in content or '"' in content


class TestClauseScopeDistinguishable:
    """Task 3.5 / spec: Clause-scoped entries are distinguishable from contract-level entries."""

    def test_clause_scoped_entry_identifies_its_clause(self, client):
        contract = ContractFactory()
        clause = ClauseFactory(contract=contract, sequence_index=7)
        AuditLogEntryFactory(contract=contract, clause=clause, stage=2)

        response = client.get(_audit_log_url(contract.id))
        content = response.content.decode()

        assert "clause-scoped" in content
        assert str(clause.id) in content

    def test_null_clause_entry_renders_as_contract_level_with_no_clause_association(
        self, client
    ):
        contract = ContractFactory()
        other_clause = ClauseFactory(contract=contract, sequence_index=0)
        AuditLogEntryFactory(contract=contract, clause=None, stage=1)

        response = client.get(_audit_log_url(contract.id))
        content = response.content.decode()

        assert "contract-level" in content
        assert str(other_clause.id) not in content


class TestChainIntegritySection:
    """Task 8.3 / spec: pipeline/audit-log-integrity - chain integrity surfaced
    on the audit-log page via the same `verify_audit_chain` the CLI command
    calls."""

    def test_untampered_chain_renders_pass(self, client):
        contract = ContractFactory()
        create_audit_log_entry(
            contract=contract,
            clause=None,
            stage=1,
            prompt_version="v1",
            llm_response_raw={"ok": True},
            model_name="test-model",
            latency_ms=1,
        )
        create_audit_log_entry(
            contract=contract,
            clause=None,
            stage=2,
            prompt_version="v1",
            llm_response_raw={"ok": True},
            model_name="test-model",
            latency_ms=1,
        )

        response = client.get(_audit_log_url(contract.id))
        content = response.content.decode()

        assert "Chain integrity" in content
        assert "PASS" in content
        assert "guardrail-pass" in content

    def test_tampered_chain_surfaces_a_break(self, client):
        contract = ContractFactory()
        entry = create_audit_log_entry(
            contract=contract,
            clause=None,
            stage=1,
            prompt_version="v1",
            llm_response_raw={"ok": True},
            model_name="test-model",
            latency_ms=1,
        )
        AuditLogEntry.objects.filter(id=entry.id).update(stage=99)

        response = client.get(_audit_log_url(contract.id))
        content = response.content.decode()

        assert "guardrail-fail" in content
        assert "break(s) found" in content
        assert str(entry.id) in content

    def test_contract_with_only_exempt_entries_shows_exempt_note_and_still_passes(self, client):
        contract = ContractFactory()
        AuditLogEntryFactory(contract=contract, stage=1)

        response = client.get(_audit_log_url(contract.id))
        content = response.content.decode()

        assert "guardrail-pass" in content
        assert "chain-exempt" in content
