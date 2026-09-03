"""Tests for report_ui.views.guardrail_verification_view (tasks 4.4-4.5).

Spec: report-ui/guardrail-verification-view. `GuardrailScanResult`/
`GuardrailViolation`/`scan_razorpay_guardrail` relocated from
`report_ui.selectors` to `reporting.selectors` in add-react-frontend - see
that change's design.md. Import path updated only; no behavior change.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse

from reporting.selectors import GuardrailScanResult, GuardrailViolation

pytestmark = pytest.mark.django_db


def _guardrail_url() -> str:
    return reverse("guardrail_verification")


class TestGuardrailViewBasics:
    def test_returns_200(self, client):
        response = client.get(_guardrail_url())

        assert response.status_code == 200


class TestScannedFileListDisclosed:
    """Task 4.4 / spec: Scanned file list is disclosed."""

    def test_every_scanned_file_path_appears_in_rendered_html(self, client):
        fake_result = GuardrailScanResult(
            passed=True,
            scanned_files=[
                "/project/razorpay_integration/client.py",
                "/project/razorpay_integration/services.py",
            ],
            violations=[],
        )
        with patch("reporting.selectors.scan_razorpay_guardrail", return_value=fake_result):
            response = client.get(_guardrail_url())

        content = response.content.decode()
        for path in fake_result.scanned_files:
            assert path in content

    def test_clean_scan_renders_an_explicit_pass(self, client):
        fake_result = GuardrailScanResult(passed=True, scanned_files=["a.py"], violations=[])
        with patch("reporting.selectors.scan_razorpay_guardrail", return_value=fake_result):
            response = client.get(_guardrail_url())

        content = response.content.decode()
        assert "PASS" in content
        assert "FAIL" not in content


class TestViolationRendersFailWithEvidence:
    """Task 4.5 / spec: A violation renders a fail with evidence."""

    def test_fail_lists_file_line_and_matched_call_for_every_violation(self, client):
        fake_result = GuardrailScanResult(
            passed=False,
            scanned_files=["/project/razorpay_integration/client.py"],
            violations=[
                GuardrailViolation(
                    file="/project/razorpay_integration/client.py",
                    line=42,
                    matched_call="sdk_client.post",
                ),
                GuardrailViolation(
                    file="/project/razorpay_integration/client.py",
                    line=99,
                    matched_call="sdk_client.delete",
                ),
            ],
        )
        with patch("reporting.selectors.scan_razorpay_guardrail", return_value=fake_result):
            response = client.get(_guardrail_url())

        content = response.content.decode()
        assert "FAIL" in content
        for violation in fake_result.violations:
            assert violation.file in content
            assert str(violation.line) in content
            assert violation.matched_call in content
