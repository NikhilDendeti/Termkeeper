"""Task 1.2: the three report_ui routes resolve by name."""

from __future__ import annotations

import uuid

from django.urls import reverse


class TestUrlsResolve:
    def test_contract_report_url_resolves(self):
        contract_id = uuid.uuid4()
        url = reverse("contract_report", kwargs={"contract_id": contract_id})
        assert str(contract_id) in url
        assert url.endswith("/report/")
        assert url.startswith("/report/")

    def test_contract_audit_log_url_resolves(self):
        contract_id = uuid.uuid4()
        url = reverse("contract_audit_log", kwargs={"contract_id": contract_id})
        assert str(contract_id) in url
        assert url.endswith("/audit-log/")
        assert url.startswith("/report/")

    def test_guardrail_verification_url_resolves(self):
        url = reverse("guardrail_verification")
        assert url == "/report/guardrail/"
