"""Management command: run the evaluation harness's scoring pass.

Usage:
    manage.py eval run --dataset eval/v1 [--fixture-version v1]
        [--minutes-per-dismissed-flag 5.0]
    manage.py eval generate-dataset --dataset eval/v1 --count 40
        --export evaluation/fixtures/dataset/v1/contracts.json

`--dataset` accepts either the bare dataset_version ("v1") or the
"eval/<version>" form design.md's proposal.md example uses
("eval/v1") - the leading "eval/" is a fixed namespace prefix, stripped
before being passed to `evaluation.services.run_eval`/`generate_dataset` as
`dataset_version`. Both subcommands share the same `_parse_dataset_version`
helper.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from evaluation.services import (
    DEFAULT_DATASET_SIZE,
    ManifestIntegrityError,
    export_dataset_snapshot,
    generate_dataset,
    run_eval,
)


def _parse_dataset_version(raw: str) -> str:
    if raw.startswith("eval/"):
        return raw[len("eval/") :]
    return raw


class Command(BaseCommand):
    help = "Run the evaluation harness's held-out scoring pass for a dataset version."

    def add_arguments(self, parser: Any) -> None:
        subparsers = parser.add_subparsers(dest="subcommand", required=True)
        run_parser = subparsers.add_parser(
            "run", help="Score the pipeline's persisted output against held-out labels."
        )
        run_parser.add_argument(
            "--dataset",
            type=str,
            required=True,
            help="Dataset version to score, e.g. eval/v1 (or bare v1).",
        )
        run_parser.add_argument(
            "--fixture-version",
            type=str,
            default="v1",
            help="Razorpay fixture matrix version to record on the EvalRun. Defaults to v1.",
        )
        run_parser.add_argument(
            "--minutes-per-dismissed-flag",
            type=float,
            default=5.0,
            help="Reviewer-minutes-per-dismissed-flag cost assumption. Defaults to 5.0.",
        )

        generate_parser = subparsers.add_parser(
            "generate-dataset",
            help="Generate, label, and export a synthetic dataset version in one step.",
        )
        generate_parser.add_argument(
            "--dataset",
            type=str,
            required=True,
            help="Dataset version to generate, e.g. eval/v1 (or bare v1).",
        )
        generate_parser.add_argument(
            "--count",
            type=int,
            default=DEFAULT_DATASET_SIZE,
            help=f"Number of contracts to generate (30-50). Defaults to {DEFAULT_DATASET_SIZE}.",
        )
        generate_parser.add_argument(
            "--export",
            type=str,
            required=True,
            help="File path to write the exported dataset snapshot JSON to.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        subcommand = options["subcommand"]
        if subcommand == "run":
            self._handle_run(options)
        elif subcommand == "generate-dataset":
            self._handle_generate_dataset(options)
        else:
            raise CommandError(f"Unknown eval subcommand {subcommand!r}")

    def _handle_run(self, options: dict[str, Any]) -> None:
        dataset_version = _parse_dataset_version(options["dataset"])

        try:
            eval_run = run_eval(
                dataset_version=dataset_version,
                fixture_version=options["fixture_version"],
                minutes_per_dismissed_flag=options["minutes_per_dismissed_flag"],
            )
        except ManifestIntegrityError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"EvalRun {eval_run.id} for dataset_version={dataset_version!r} "
                f"(fixture_version={eval_run.fixture_version!r})"
            )
        )
        self.stdout.write(
            json.dumps(
                {
                    "precision_recall_f1": eval_run.precision_recall_f1,
                    "severity_calibration_score": eval_run.severity_calibration_score,
                    "cost_report": eval_run.cost_report,
                    "false_positive_cost_note": eval_run.false_positive_cost_note,
                    "pipeline_version": eval_run.pipeline_version,
                    "prompt_version": eval_run.prompt_version,
                },
                indent=2,
                default=str,
            )
        )

    def _handle_generate_dataset(self, options: dict[str, Any]) -> None:
        dataset_version = _parse_dataset_version(options["dataset"])
        count = options["count"]

        try:
            contracts = generate_dataset(dataset_version=dataset_version, count=count)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        snapshot = export_dataset_snapshot(dataset_version=dataset_version)

        export_path = Path(options["export"])
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {len(contracts)} contracts for dataset_version={dataset_version!r} "
                f"and exported {len(snapshot['contracts'])} entries to {export_path}"
            )
        )
