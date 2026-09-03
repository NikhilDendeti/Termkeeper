"""Tests for contracts.selectors.list_contracts (task 2.1).

Spec: api/contract-listing (Scenario: Contracts returned newest first;
Scenario: Empty project returns an empty list).

Located under `reporting/tests/` rather than `contracts/tests/`: this
change's file ownership scopes `contracts/` edits to adding
`list_contracts` itself only, so its accompanying unit test lives here
instead, importing `contracts.selectors.list_contracts` and
`contracts.tests.factories` directly - `reporting` already depends on
`contracts` (see `reporting/selectors.py`), so this is consistent with the
existing dependency direction.
"""

from __future__ import annotations

import pytest

from contracts.selectors import list_contracts
from contracts.tests.factories import ContractFactory

pytestmark = pytest.mark.django_db


class TestListContractsNewestFirst:
    def test_contracts_returned_newest_created_first(self):
        first = ContractFactory()
        second = ContractFactory()
        third = ContractFactory()

        contracts = list(list_contracts())

        assert [c.id for c in contracts] == [third.id, second.id, first.id]


class TestListContractsEmptyProject:
    def test_empty_project_returns_empty_list(self):
        contracts = list(list_contracts())

        assert contracts == []
