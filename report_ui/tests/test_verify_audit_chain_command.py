"""Tests for report_ui's `verify_audit_chain` management command (task 7.2).

Mirrors `test_verify_guardrail_command.py`'s shape: `manage.py
verify_audit_chain` exits 0 on a clean scan and non-zero (via `CommandError`
raised from `handle()`) on a scan that finds a break - the same mechanism
Django's `execute_from_command_line` turns into `sys.exit(1)` for a real CLI
invocation. The clean-scan (exit 0) side is also checked end-to-end via a
real subprocess against this project's actual `db.sqlite3` data.
"""

from __future__ import annotations

import subprocess
import sys
import uuid

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from contracts.tests.factories import ContractFactory
from pipeline.models import AuditLogEntry
from pipeline.services import create_audit_log_entry

pytestmark = pytest.mark.django_db


def _write_entry(contract, *, stage=1):
    return create_audit_log_entry(
        contract=contract,
        clause=None,
        stage=stage,
        prompt_version="v1",
        llm_response_raw={"ok": True},
        model_name="test-model",
        latency_ms=1,
    )


class TestVerifyAuditChainCommandCleanScan:
    def test_exits_zero_against_the_real_currently_clean_db(self):
        result = subprocess.run(
            [sys.executable, "manage.py", "verify_audit_chain"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(settings.BASE_DIR),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS" in result.stdout

    def test_handle_does_not_raise_when_chain_is_clean(self, capsys):
        contract = ContractFactory()
        _write_entry(contract, stage=1)
        _write_entry(contract, stage=2)

        call_command("verify_audit_chain")

        captured = capsys.readouterr()
        assert "PASS" in captured.out

    def test_scopes_to_one_contract_via_contract_id_flag(self, capsys):
        contract = ContractFactory()
        _write_entry(contract, stage=1)

        call_command("verify_audit_chain", contract_id=str(contract.id))

        captured = capsys.readouterr()
        assert "Contracts checked: 1" in captured.out
        assert "PASS" in captured.out


class TestVerifyAuditChainCommandBreakFound:
    def test_handle_raises_command_error_when_a_break_is_found(self, capsys):
        contract = ContractFactory()
        entry = _write_entry(contract, stage=1)
        AuditLogEntry.objects.filter(id=entry.id).update(stage=99)

        with pytest.raises(CommandError):
            call_command("verify_audit_chain")

        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert str(entry.chain_sequence) in captured.out

    def test_unknown_contract_id_raises(self):
        from contracts.models import Contract

        with pytest.raises(Contract.DoesNotExist):
            call_command("verify_audit_chain", contract_id=str(uuid.uuid4()))
