"""Tests for report_ui's `verify_guardrail` management command (task 4.7).

`manage.py verify_guardrail` exits 0 on a clean scan and 1 on a scan with
at least one violation - a `CommandError` raised from `handle()` is exactly
what causes Django's `execute_from_command_line` to print the error and
`sys.exit(1)` when the command is actually invoked from a shell (see
Django's `ManagementUtility.execute`), so asserting that `CommandError` is
raised for a failing scan verifies the same non-zero-exit behavior a real
CLI invocation would produce. The clean-scan (exit 0) side is also checked
end-to-end via a real subprocess against this project's actual, currently-
passing razorpay_integration source.
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from reporting.selectors import GuardrailScanResult, GuardrailViolation


class TestVerifyGuardrailCommandCleanScan:
    def test_exits_zero_against_the_real_currently_clean_production_path(self):
        result = subprocess.run(
            [sys.executable, "manage.py", "verify_guardrail"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(settings.BASE_DIR),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS" in result.stdout

    def test_handle_does_not_raise_when_scan_passes(self, capsys):
        fake_result = GuardrailScanResult(passed=True, scanned_files=["a.py"], violations=[])
        with patch(
            "report_ui.management.commands.verify_guardrail.scan_razorpay_guardrail",
            return_value=fake_result,
        ):
            call_command("verify_guardrail")

        captured = capsys.readouterr()
        assert "PASS" in captured.out


class TestVerifyGuardrailCommandViolationFound:
    def test_handle_raises_command_error_when_scan_fails(self, capsys):
        fake_result = GuardrailScanResult(
            passed=False,
            scanned_files=["a.py"],
            violations=[GuardrailViolation(file="a.py", line=1, matched_call="sdk_client.post")],
        )
        with patch(
            "report_ui.management.commands.verify_guardrail.scan_razorpay_guardrail",
            return_value=fake_result,
        ):
            with pytest.raises(CommandError):
                call_command("verify_guardrail")

        captured = capsys.readouterr()
        assert "FAIL" in captured.out
