"""Test-mode Razorpay fixture / demo-seeding.

The ONLY place in `razorpay_integration` (or anywhere in this project) that
ever issues a write (POST/PUT/PATCH/DELETE) call against Razorpay. Neither
`services.py` nor `client.py` imports this module, and `detect_mismatches`'
transitive import graph never reaches it - see
tests/test_fixtures_isolation.py and design.md (add-razorpay-crosscheck) -
"razorpay_integration/fixtures.py - the only place writes happen."

This module is invoked only from management commands or test setup,
explicitly, never from the pipeline. It exists to seed demo/dev data
(Contact, Fund Account, Payout, Subscription, Token) using Razorpay's
documented test-mode dummy values, never to touch a real user's live
account data.
"""

from __future__ import annotations

from typing import Any

import razorpay
from django.conf import settings

# Razorpay's documented test-mode dummy bank account/IFSC values - never
# real account data. See design.md - Risks ("India-only IFSC/account-number
# validation could block demo fund-account setup entirely").
TEST_MODE_IFSC = "HDFC0000053"
TEST_MODE_ACCOUNT_NUMBER = "765432123456789"


def _test_mode_client() -> razorpay.Client:
    """Build a razorpay.Client using this environment's test-mode credentials."""
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def seed_contact(
    *, name: str, email: str, contact_type: str = "vendor", client: razorpay.Client | None = None
) -> dict[str, Any]:
    """POST /v1/contacts - create a test-mode RazorpayX Contact."""
    sdk_client = client or _test_mode_client()
    data = {"name": name, "email": email, "type": contact_type}
    result: dict[str, Any] = sdk_client.post("/v1/contacts", data)
    return result


def seed_fund_account(
    *, contact_id: str, account_holder_name: str, client: razorpay.Client | None = None
) -> dict[str, Any]:
    """POST /v1/fund_accounts - create a test-mode Fund Account for a Contact.

    Uses Razorpay's documented dummy IFSC/account-number values - never a
    real bank account.
    """
    sdk_client = client or _test_mode_client()
    data = {
        "contact_id": contact_id,
        "account_type": "bank_account",
        "bank_account": {
            "name": account_holder_name,
            "ifsc": TEST_MODE_IFSC,
            "account_number": TEST_MODE_ACCOUNT_NUMBER,
        },
    }
    result: dict[str, Any] = sdk_client.post("/v1/fund_accounts", data)
    return result


def seed_payout(
    *,
    fund_account_id: str,
    account_number: str,
    amount_paise: int,
    purpose: str = "payout",
    client: razorpay.Client | None = None,
) -> dict[str, Any]:
    """POST /v1/payouts - create one test-mode Payout against a Fund Account."""
    sdk_client = client or _test_mode_client()
    data = {
        "account_number": account_number,
        "fund_account_id": fund_account_id,
        "amount": amount_paise,
        "currency": "INR",
        "mode": "IMPS",
        "purpose": purpose,
        "queue_if_low_balance": True,
    }
    result: dict[str, Any] = sdk_client.post("/v1/payouts", data)
    return result


def seed_subscription(
    *,
    plan_id: str,
    total_count: int,
    customer_notify: bool = True,
    client: razorpay.Client | None = None,
) -> dict[str, Any]:
    """POST /v1/subscriptions - create a test-mode Subscription."""
    sdk_client = client or _test_mode_client()
    data = {
        "plan_id": plan_id,
        "total_count": total_count,
        "customer_notify": 1 if customer_notify else 0,
    }
    result: dict[str, Any] = sdk_client.subscription.create(data)
    return result


def seed_token(
    *,
    customer_id: str,
    method: str = "upi",
    max_amount_paise: int = 500000,
    client: razorpay.Client | None = None,
) -> dict[str, Any]:
    """POST /v1/tokens - create a test-mode UPI Autopay Token for a Customer.

    Card tokens expire after 3 days in test mode (see design.md - Risks);
    callers seeding demo data should re-seed if a previously created token
    has expired.
    """
    sdk_client = client or _test_mode_client()
    data = {
        "customer_id": customer_id,
        "method": method,
        "max_amount": max_amount_paise,
        "recurring_details": {"status": "confirmed"},
    }
    result: dict[str, Any] = sdk_client.token.create(data)
    return result
