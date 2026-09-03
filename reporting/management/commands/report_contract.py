"""Management command: print a Contract's aggregate risk report and audit trail.

Usage:
    manage.py report_contract --contract-id <uuid> [--format json|md]

Delegates to the exact same `reporting.selectors.get_contract_report` and
`reporting.selectors.get_full_audit_trail` the DRF endpoints call, and
serializes the JSON path through the same serializers, so CLI/API content
never drifts - see design.md (add-risk-scoring-report) - "CLI/API parity is
structural, not tested-after-the-fact."
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from contracts.models import Contract
from contracts.selectors import get_contract
from pipeline.models import AuditLogEntry
from reporting.selectors import get_contract_report, get_full_audit_trail
from reporting.serializers import AuditLogEntrySerializer, ContractReportSerializer

_SUPPORTED_FORMATS = ("json", "md")


class Command(BaseCommand):
    help = "Print a Contract's aggregate risk report and full audit trail."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--contract-id",
            type=str,
            required=True,
            help="UUID of the Contract to report on.",
        )
        parser.add_argument(
            "--format",
            type=str,
            default="json",
            help="Output format: json or md. Defaults to json.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        fmt = options["format"]
        if fmt not in _SUPPORTED_FORMATS:
            raise CommandError(
                f"Unsupported --format {fmt!r}; expected one of {_SUPPORTED_FORMATS!r}."
            )

        raw_contract_id = options["contract_id"]
        try:
            contract_id = uuid.UUID(raw_contract_id)
        except ValueError as exc:
            raise CommandError(f"Invalid --contract-id: {raw_contract_id!r}") from exc

        try:
            contract = get_contract(contract_id=contract_id)
        except Contract.DoesNotExist as exc:
            raise CommandError(f"No Contract found with id {contract_id}") from exc

        report = get_contract_report(contract=contract)
        audit_entries = list(get_full_audit_trail(contract=contract))

        if fmt == "json":
            self.stdout.write(self._render_json(report=report, audit_entries=audit_entries))
        else:
            self.stdout.write(self._render_markdown(report=report, audit_entries=audit_entries))

    def _render_json(
        self, *, report: dict[str, Any], audit_entries: list[AuditLogEntry]
    ) -> str:
        payload = {
            "report": ContractReportSerializer(instance=report).data,
            "audit_trail": AuditLogEntrySerializer(instance=audit_entries, many=True).data,
        }
        return json.dumps(payload, default=str)

    def _render_markdown(
        self, *, report: dict[str, Any], audit_entries: list[AuditLogEntry]
    ) -> str:
        lines: list[str] = []
        score = report["overall_risk_score"]
        lines.append(f"# Risk Report for Contract {report['contract_id']}")
        lines.append("")
        lines.append(
            f"**Overall risk score:** "
            f"{score if score is not None else 'N/A (no scored clauses yet)'}"
        )
        lines.append("")

        lines.append("## Flagged Clauses")
        if not report["flagged_clauses"]:
            lines.append("(none)")
        for clause in report["flagged_clauses"]:
            lines.append(
                f"- Clause {clause['clause_id']} (sequence {clause['sequence_index']}, "
                f"type={clause['clause_type']}): severity={clause['severity']}, "
                f"asymmetry_score={clause['asymmetry_score']}"
            )
            lines.append(f"  - Explanation: {clause['explanation']}")
            if clause["suggested_rewrite"]:
                lines.append(f"  - Suggested rewrite: {clause['suggested_rewrite']}")
            if clause["linked_mismatch_flag_ids"]:
                linked = ", ".join(clause["linked_mismatch_flag_ids"])
                lines.append(f"  - Linked mismatch ids: {linked}")
        lines.append("")

        lines.append("## Platform Mismatches")
        if not report["platform_mismatches"]:
            lines.append("(none)")
        for mismatch in report["platform_mismatches"]:
            lines.append(
                f"- Mismatch {mismatch['mismatch_id']} ({mismatch['mismatch_type']}) on "
                f"clause {mismatch['clause_id']} (sequence {mismatch['sequence_index']}): "
                f"{mismatch['description']}"
            )
        lines.append("")

        lines.append("## Needs Human Review")
        if not report["needs_human_review_clauses"]:
            lines.append("(none)")
        for clause in report["needs_human_review_clauses"]:
            lines.append(
                f"- Clause {clause['clause_id']} (sequence {clause['sequence_index']}, "
                f"type={clause['clause_type']}): {clause['explanation']}"
            )
        lines.append("")

        lines.append("## Audit Trail")
        if not audit_entries:
            lines.append("(none)")
        for entry in audit_entries:
            lines.append(
                f"- [stage {entry.stage}] {entry.prompt_version} "
                f"(model={entry.model_name}, latency_ms={entry.latency_ms}, "
                f"created_at={entry.created_at.isoformat()})"
            )

        return "\n".join(lines)
