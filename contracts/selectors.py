"""Read-path selector functions for the `contracts` app.

Every non-trivial read goes through a function here per project convention.
"""

import uuid

from django.db.models import QuerySet

from contracts.models import Clause, Contract


def get_contract(*, contract_id: uuid.UUID) -> Contract:
    """Fetch a single Contract by id.

    Raises:
        Contract.DoesNotExist: if no Contract with that id exists.
    """
    return Contract.objects.get(id=contract_id)


def list_clauses_for_contract(*, contract: Contract) -> QuerySet[Clause]:
    """List a Contract's clauses ordered by `sequence_index` (source order)."""
    return contract.clauses.order_by("sequence_index")


def list_contracts() -> QuerySet[Contract]:
    """List every ingested Contract, newest-created first.

    See specs/api/contract-listing/spec.md (Scenario: Contracts returned
    newest first).
    """
    return Contract.objects.order_by("-created_at")
