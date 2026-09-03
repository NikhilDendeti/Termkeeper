"""Management command: run (or resume) the pipeline for a Contract.

Usage:
    manage.py run_pipeline --contract-id <uuid> [--from-stage 1|2|3]

Stages: 1=segmentation, 2=classification, 3=extraction (default: 1, i.e. a
full run). `--from-stage 2` resumes a Contract that already has Clause rows
from an earlier stage-1 run, re-reading them from the database rather than
re-running segmentation.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from contracts.models import Contract
from contracts.selectors import get_contract
from pipeline.services import run_pipeline


class Command(BaseCommand):
    help = "Run the pipeline (segmentation, classification, extraction) for a Contract."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--contract-id",
            type=str,
            required=True,
            help="UUID of the Contract to run the pipeline for.",
        )
        parser.add_argument(
            "--from-stage",
            type=int,
            default=1,
            choices=[1, 2, 3],
            help=(
                "Stage to start/resume from: 1=segmentation, "
                "2=classification, 3=extraction. Defaults to 1 (a full run)."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        raw_contract_id = options["contract_id"]
        try:
            contract_id = uuid.UUID(raw_contract_id)
        except ValueError as exc:
            raise CommandError(f"Invalid --contract-id: {raw_contract_id!r}") from exc

        try:
            contract = get_contract(contract_id=contract_id)
        except Contract.DoesNotExist as exc:
            raise CommandError(f"No Contract found with id {contract_id}") from exc

        from_stage = options["from_stage"]
        run_pipeline(contract=contract, from_stage=from_stage)

        self.stdout.write(
            self.style.SUCCESS(
                f"Ran pipeline for Contract {contract.id} starting at stage {from_stage}."
            )
        )
