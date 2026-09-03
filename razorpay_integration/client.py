"""Read-only Razorpay connector.

Every call that pipeline stage 4 (`detect_mismatches`) can reach funnels
through this module, and every one of those calls is a GET. Test-mode
fixture/demo-seeding writes (POST) live entirely in
`razorpay_integration/fixtures.py`, a module this one never imports - see
design.md (add-razorpay-crosscheck) - "razorpay_integration/client.py -
read-only connector" and the "No claim of a payout schedule configuration"
/ guardrail requirements.

`RazorpayConnector` exposes exactly three methods used by the production
path: `fetch_payouts`, `fetch_subscription`, `fetch_token`. Each is backed
primarily by the `razorpay` Python SDK; a raw-`requests` fallback (`_raw_get`)
is used only when the installed SDK does not expose the needed attribute
(e.g. this SDK ships no dedicated Payout resource class for RazorpayX
Payouts - see proposal.md's "New dependency" note).
"""

from __future__ import annotations

from typing import Any

import razorpay
import requests
from django.conf import settings

_BASE_URL = "https://api.razorpay.com"
_PAYOUTS_PATH = "/v1/payouts"
_SUBSCRIPTIONS_PATH = "/v1/subscriptions"
_CUSTOMERS_PATH = "/v1/customers"

_REQUEST_TIMEOUT_SECONDS = 30


class RazorpayConnector:
    """GET-only wrapper around the razorpay SDK, with a raw-requests fallback.

    No method here, nor anything it calls, ever issues a POST/PUT/PATCH/
    DELETE request. Enforced by a static-scan test
    (tests/test_client.py::test_client_source_contains_no_write_verbs) and a
    dynamic mocked-transport test
    (tests/test_guardrails.py::test_connector_only_ever_dispatches_get_requests).
    """

    def __init__(self, *, key_id: str | None = None, key_secret: str | None = None) -> None:
        self._key_id = key_id if key_id is not None else settings.RAZORPAY_KEY_ID
        self._key_secret = key_secret if key_secret is not None else settings.RAZORPAY_KEY_SECRET
        self._sdk_client = razorpay.Client(auth=(self._key_id, self._key_secret))

    def fetch_payouts(self, *, fund_account_id: str) -> dict[str, Any]:
        """GET /v1/payouts filtered by fund_account_id (RazorpayX Payout history).

        RazorpayX Payouts has no queryable schedule-configuration endpoint -
        only this raw history is available via API (see design.md - Context).
        """
        params = {"fund_account_id": fund_account_id}
        try:
            # `Client.get` is the SDK's own low-level GET dispatcher - used
            # directly since this SDK version ships no dedicated Payout
            # resource wrapper.
            result: dict[str, Any] = self._sdk_client.get(_PAYOUTS_PATH, params)
            return result
        except AttributeError:
            return self._raw_get(_PAYOUTS_PATH, params=params)

    def fetch_subscription(self, *, subscription_id: str) -> dict[str, Any]:
        """GET /v1/subscriptions/{subscription_id}."""
        try:
            result: dict[str, Any] = self._sdk_client.subscription.fetch(subscription_id)
            return result
        except AttributeError:
            return self._raw_get(f"{_SUBSCRIPTIONS_PATH}/{subscription_id}")

    def fetch_token(self, *, customer_id: str) -> dict[str, Any]:
        """GET /v1/customers/{customer_id}/tokens - every token for the customer.

        Returns the raw collection response; the caller selects which token
        to diff against (the one with the latest `razorpay_created_at` that
        is not cancelled) - see design.md "Token resolution for the
        subscription path."
        """
        try:
            result: dict[str, Any] = self._sdk_client.token.all(customer_id)
            return result
        except AttributeError:
            return self._raw_get(f"{_CUSTOMERS_PATH}/{customer_id}/tokens")

    def _raw_get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Raw-`requests` fallback GET, used only when the SDK lacks a resource."""
        response = requests.get(
            f"{_BASE_URL}{path}",
            params=params,
            auth=(self._key_id, self._key_secret),
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result
