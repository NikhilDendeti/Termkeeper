"""Management command: verify razorpay_integration's no-write-calls guardrail.

Wraps the exact same `reporting.selectors.scan_razorpay_guardrail` the
guardrail-verification page calls, for CI/local use - see design.md
(add-report-ui) - Decisions. `scan_razorpay_guardrail` relocated from
`report_ui.selectors` to `reporting.selectors` in add-react-frontend - see
that change's design.md; this import updated accordingly, no behavior
change. Prints the scanned file list and result; raises `CommandError`
(non-zero exit when invoked as `manage.py verify_guardrail`) when the scan
finds any violation.

Usage:
    manage.py verify_guardrail
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from reporting.selectors import scan_razorpay_guardrail


class Command(BaseCommand):
    help = "Statically scan razorpay_integration's production path for write calls."

    def handle(self, *args: Any, **options: Any) -> None:
        result = scan_razorpay_guardrail()

        self.stdout.write("Scanned files:")
        for file_path in result.scanned_files:
            self.stdout.write(f"  - {file_path}")

        if result.passed:
            self.stdout.write(self.style.SUCCESS("PASS: no write calls found."))
            return

        self.stdout.write(self.style.ERROR("FAIL: write call(s) found:"))
        for violation in result.violations:
            self.stdout.write(
                f"  - {violation.file}:{violation.line} matched_call={violation.matched_call!r}"
            )
        raise CommandError(
            f"Guardrail scan failed: {len(result.violations)} write-call violation(s) found."
        )
