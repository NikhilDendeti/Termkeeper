"""Management command: verify every AuditLogEntry hash chain (or one Contract's).

Wraps the exact same `reporting.selectors.verify_audit_chain` the
per-contract audit-log page calls, for CI/local use - mirrors
`verify_guardrail.py`'s shape line for line. See design.md
(add-audit-log-hash-chain) - "The verification command". Prints a
per-contract summary (contracts checked, entries verified, entries exempt),
prints any breaks, and raises `CommandError` (non-zero exit when invoked as
`manage.py verify_audit_chain`) when the result's `passed` is `False`.

Usage:
    manage.py verify_audit_chain
    manage.py verify_audit_chain --contract-id <uuid>
"""

from __future__ import annotations

import uuid
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from contracts import selectors as contracts_selectors
from reporting.selectors import verify_audit_chain


class Command(BaseCommand):
    help = "Recompute and verify every AuditLogEntry hash chain (or one Contract's)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--contract-id",
            type=str,
            default=None,
            help="Scope verification to one Contract's chain, by id.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        contract = None
        contract_id_arg = options.get("contract_id")
        if contract_id_arg:
            contract = contracts_selectors.get_contract(contract_id=uuid.UUID(contract_id_arg))

        result = verify_audit_chain(contract=contract)

        self.stdout.write(f"Contracts checked: {result.contracts_checked}")
        self.stdout.write(f"Entries verified: {result.entries_verified}")
        self.stdout.write(f"Entries exempt (pre-existing, no hash): {result.entries_exempt}")

        if result.passed:
            self.stdout.write(self.style.SUCCESS("PASS: no hash-chain breaks found."))
            return

        self.stdout.write(self.style.ERROR("FAIL: hash-chain break(s) found:"))
        for chain_break in result.breaks:
            self.stdout.write(
                f"  - contract_id={chain_break.contract_id} "
                f"entry_id={chain_break.entry_id} "
                f"chain_sequence={chain_break.chain_sequence} "
                f"reason={chain_break.reason!r}"
            )
        raise CommandError(
            f"Audit chain verification failed: {len(result.breaks)} break(s) found."
        )
