"""Tests for evaluation.selectors.list_eval_fixture_contract_ids."""

from __future__ import annotations

import pytest

from contracts.tests.factories import ClauseFactory, ContractFactory
from evaluation.selectors import list_eval_fixture_contract_ids
from evaluation.tests.factories import EvalLabelFactory

pytestmark = pytest.mark.django_db


class TestListEvalFixtureContractIds:
    def test_no_fixtures_returns_empty_set(self):
        ContractFactory()

        assert list_eval_fixture_contract_ids() == set()

    def test_contract_with_an_eval_label_is_included(self):
        contract = ContractFactory()
        EvalLabelFactory(contract=contract, clause=ClauseFactory(contract=contract))

        assert list_eval_fixture_contract_ids() == {contract.id}

    def test_a_real_contract_with_no_eval_label_is_not_included(self):
        real_contract = ContractFactory()
        fixture_contract = ContractFactory()
        EvalLabelFactory(
            contract=fixture_contract, clause=ClauseFactory(contract=fixture_contract)
        )

        ids = list_eval_fixture_contract_ids()

        assert ids == {fixture_contract.id}
        assert real_contract.id not in ids

    def test_multiple_labels_on_one_contract_still_yield_one_id(self):
        contract = ContractFactory()
        clause = ClauseFactory(contract=contract)
        EvalLabelFactory(contract=contract, clause=clause)
        EvalLabelFactory(contract=contract, clause=clause)

        assert list_eval_fixture_contract_ids() == {contract.id}
