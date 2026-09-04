"""HIGH finding: a bad/deleted contract_id (or any unhandled server error)
should render inside the app's chrome via templates/404.html and
templates/500.html, not Django's bare default error page.

Django only dispatches to these custom templates when DEBUG=False (with
DEBUG=True it shows its own technical debug pages instead), so these tests
flip DEBUG off via the `settings` fixture for the duration of the test.

The 500 case needs `Client(raise_request_exception=False)`: by default the
Django test client re-raises the original exception after the response is
generated (so failures are easy to debug), which would defeat a test that
wants to inspect the rendered 500 response itself.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from contracts.tests.factories import ContractFactory

pytestmark = pytest.mark.django_db


class TestCustom404Page:
    def test_unknown_contract_id_renders_custom_404_inside_app_chrome(self, client, settings):
        settings.DEBUG = False

        url = reverse("contract_report", kwargs={"contract_id": uuid.uuid4()})
        response = client.get(url)

        assert response.status_code == 404
        content = response.content.decode()
        # Rendered via report_ui/base.html, not Django's bare default 404 page.
        assert "Payment Terms &amp; Vendor Risk Analyzer" in content
        assert "site-nav" in content
        assert "Page not found" in content


class TestCustom500Page:
    def test_unhandled_exception_renders_custom_500_inside_app_chrome(self, settings):
        settings.DEBUG = False
        contract = ContractFactory()
        error_client = Client(raise_request_exception=False)
        url = reverse("contract_report", kwargs={"contract_id": contract.id})

        with patch(
            "report_ui.views.reporting_selectors.get_contract_report",
            side_effect=RuntimeError("boom"),
        ):
            response = error_client.get(url)

        assert response.status_code == 500
        content = response.content.decode()
        assert "Payment Terms &amp; Vendor Risk Analyzer" in content
        assert "site-nav" in content
        assert "Something went wrong" in content
