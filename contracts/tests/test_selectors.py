import uuid

import pytest

from contracts.models import Contract
from contracts.selectors import get_contract, list_clauses_for_contract
from contracts.tests.factories import ClauseFactory, ContractFactory

pytestmark = pytest.mark.django_db


class TestGetContract:
    def test_returns_the_matching_contract(self):
        contract = ContractFactory()

        fetched = get_contract(contract_id=contract.id)

        assert fetched.id == contract.id

    def test_raises_does_not_exist_for_unknown_id(self):
        with pytest.raises(Contract.DoesNotExist):
            get_contract(contract_id=uuid.uuid4())


class TestListClausesForContract:
    def test_clauses_returned_ordered_by_sequence_index(self):
        contract = ContractFactory()
        # Deliberately create out of order to prove ordering isn't accidental
        # (e.g. isn't just insertion/PK order).
        ClauseFactory(contract=contract, sequence_index=2, clause_text="Third clause text.")
        ClauseFactory(contract=contract, sequence_index=0, clause_text="First clause text.")
        ClauseFactory(contract=contract, sequence_index=1, clause_text="Second clause text.")

        clauses = list(list_clauses_for_contract(contract=contract))

        assert [c.sequence_index for c in clauses] == [0, 1, 2]
        assert [c.clause_text for c in clauses] == [
            "First clause text.",
            "Second clause text.",
            "Third clause text.",
        ]

    def test_only_returns_clauses_for_the_given_contract(self):
        contract_a = ContractFactory()
        contract_b = ContractFactory()
        ClauseFactory(contract=contract_a, sequence_index=0)
        other_clause = ClauseFactory(contract=contract_b, sequence_index=0)

        clauses = list(list_clauses_for_contract(contract=contract_a))

        assert other_clause not in clauses
        assert all(c.contract_id == contract_a.id for c in clauses)

    def test_empty_for_contract_with_no_clauses(self):
        contract = ContractFactory()

        clauses = list(list_clauses_for_contract(contract=contract))

        assert clauses == []
