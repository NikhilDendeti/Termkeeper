"""Task 5.2: cross-links between the three report_ui pages all resolve."""

from __future__ import annotations

import pytest
from django.urls import reverse

from contracts.tests.factories import ClauseFactory, ContractFactory

pytestmark = pytest.mark.django_db


class TestCrossPageNavigation:
    def test_report_page_links_to_audit_log_and_guardrail_pages(self, client):
        contract = ContractFactory()
        ClauseFactory(contract=contract, sequence_index=0)

        report_url = reverse("contract_report", kwargs={"contract_id": contract.id})
        audit_log_url = reverse("contract_audit_log", kwargs={"contract_id": contract.id})
        guardrail_url = reverse("guardrail_verification")

        response = client.get(report_url)
        content = response.content.decode()

        assert f'href="{audit_log_url}"' in content
        assert f'href="{guardrail_url}"' in content
        assert client.get(audit_log_url).status_code == 200
        assert client.get(guardrail_url).status_code == 200

    def test_audit_log_page_links_to_report_and_guardrail_pages(self, client):
        contract = ContractFactory()

        report_url = reverse("contract_report", kwargs={"contract_id": contract.id})
        audit_log_url = reverse("contract_audit_log", kwargs={"contract_id": contract.id})
        guardrail_url = reverse("guardrail_verification")

        response = client.get(audit_log_url)
        content = response.content.decode()

        assert f'href="{report_url}"' in content
        assert f'href="{guardrail_url}"' in content
        assert client.get(report_url).status_code == 200
        assert client.get(guardrail_url).status_code == 200

    def test_guardrail_page_links_are_present_and_resolve(self, client):
        guardrail_url = reverse("guardrail_verification")

        response = client.get(guardrail_url)

        assert response.status_code == 200
        # The guardrail page has no contract in context, so it shows no
        # contract-scoped links - only itself in the nav.
        assert f'href="{guardrail_url}"' in response.content.decode()
