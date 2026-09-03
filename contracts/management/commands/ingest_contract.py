"""Management command: ingest a contract file as a new Contract row.

Usage:
    manage.py ingest_contract path/to/contract.txt \
        --engagement-id ENG-123 \
        --razorpay-reference-type payout \
        --razorpay-reference-id pout_ABC123
"""

import os

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from contracts.models import RazorpayReferenceType
from contracts.services import create_contract


class Command(BaseCommand):
    help = "Create a Contract from a raw-text file plus engagement/Razorpay metadata."

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path",
            type=str,
            help="Path to a plain-text file containing the contract's raw text.",
        )
        parser.add_argument(
            "--engagement-id",
            type=str,
            required=True,
            help="Engagement identifier this contract belongs to.",
        )
        parser.add_argument(
            "--razorpay-reference-type",
            type=str,
            required=True,
            choices=[choice.value for choice in RazorpayReferenceType],
            help="Type of live Razorpay resource this contract cross-checks against.",
        )
        parser.add_argument(
            "--razorpay-reference-id",
            type=str,
            required=True,
            help="Id of the live Razorpay resource (payout or subscription).",
        )
        parser.add_argument(
            "--source-filename",
            type=str,
            default=None,
            help="Filename to record as the source (defaults to file_path's basename).",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]

        if not os.path.isfile(file_path):
            raise CommandError(f"No such file: {file_path}")

        with open(file_path, encoding="utf-8") as f:
            raw_text = f.read()

        source_filename = options["source_filename"] or os.path.basename(file_path)

        try:
            contract = create_contract(
                raw_text=raw_text,
                engagement_id=options["engagement_id"],
                razorpay_reference_type=options["razorpay_reference_type"],
                razorpay_reference_id=options["razorpay_reference_id"],
                source_filename=source_filename,
            )
        except ValidationError as exc:
            raise CommandError(f"Could not create contract: {exc.message_dict}") from exc

        self.stdout.write(self.style.SUCCESS(f"Created Contract {contract.id}"))
