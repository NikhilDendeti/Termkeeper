"""Tests for razorpay_integration.client.RazorpayConnector.

Every real network call is mocked - either at the `razorpay.Client.request`
dispatch layer (which every SDK verb funnels through) or via `requests.get`
for the raw-requests fallback path. No test in this module makes a real
network call.
"""

from __future__ import annotations

import ast
import inspect
from unittest.mock import MagicMock, patch

from razorpay_integration import client as client_module
from razorpay_integration.client import RazorpayConnector

# Any call to a method with one of these names, anywhere reachable from
# client.py, would be a write against a live Razorpay resource - the
# production cross-check path must never issue one.
_FORBIDDEN_VERB_METHOD_NAMES = frozenset(
    {"post", "put", "patch", "delete", "post_url", "put_url", "patch_url", "delete_url"}
)


def _called_method_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


class TestClientSourceGuardrail:
    """Requirement: production cross-check path issues GET calls only."""

    def test_client_source_contains_no_write_verb_calls(self):
        source = inspect.getsource(client_module)

        called_names = _called_method_names(source)

        forbidden_calls_found = called_names & _FORBIDDEN_VERB_METHOD_NAMES
        assert forbidden_calls_found == set(), (
            f"client.py calls forbidden write-verb method(s): {forbidden_calls_found!r} - "
            "the production cross-check path must issue GET calls only."
        )

    def test_client_source_contains_no_raw_write_verb_requests(self):
        source = inspect.getsource(client_module)

        assert "requests.post(" not in source
        assert "requests.put(" not in source
        assert "requests.patch(" not in source
        assert "requests.delete(" not in source


class TestRazorpayConnectorFetchPayouts:
    def test_fetch_payouts_issues_a_get_and_returns_raw_response(self):
        connector = RazorpayConnector(key_id="rzp_test_id", key_secret="rzp_test_secret")
        fake_response = {"entity": "collection", "count": 2, "items": [{"id": "pout_1"}]}

        with patch.object(connector._sdk_client, "get", return_value=fake_response) as mock_get:
            result = connector.fetch_payouts(fund_account_id="fa_00000000000001")

        assert result == fake_response
        mock_get.assert_called_once_with("/v1/payouts", {"fund_account_id": "fa_00000000000001"})


class TestRazorpayConnectorFetchSubscription:
    def test_fetch_subscription_issues_a_get_and_returns_raw_response(self):
        connector = RazorpayConnector(key_id="rzp_test_id", key_secret="rzp_test_secret")
        fake_response = {"id": "sub_1", "period": "monthly", "interval": 1}

        with patch.object(
            connector._sdk_client.subscription, "fetch", return_value=fake_response
        ) as mock_fetch:
            result = connector.fetch_subscription(subscription_id="sub_1")

        assert result == fake_response
        mock_fetch.assert_called_once_with("sub_1")


class TestRazorpayConnectorFetchToken:
    def test_fetch_token_issues_a_get_and_returns_raw_response(self):
        connector = RazorpayConnector(key_id="rzp_test_id", key_secret="rzp_test_secret")
        fake_response = {"entity": "collection", "items": [{"id": "token_1", "status": "active"}]}

        with patch.object(
            connector._sdk_client.token, "all", return_value=fake_response
        ) as mock_all:
            result = connector.fetch_token(customer_id="cust_1")

        assert result == fake_response
        mock_all.assert_called_once_with("cust_1")


class TestRazorpayConnectorRawRequestsFallback:
    """The raw-requests fallback engages only when the SDK lacks the needed attribute."""

    def test_fetch_token_falls_back_to_raw_requests_when_sdk_lacks_the_attribute(self):
        connector = RazorpayConnector(key_id="rzp_test_id", key_secret="rzp_test_secret")
        del connector._sdk_client.token  # simulate an SDK build missing this resource

        fake_response = MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {"items": []}

        with patch(
            "razorpay_integration.client.requests.get", return_value=fake_response
        ) as mock_get:
            result = connector.fetch_token(customer_id="cust_1")

        assert result == {"items": []}
        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        assert called_url.endswith("/v1/customers/cust_1/tokens")
