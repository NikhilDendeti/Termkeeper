import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from contracts.models import Contract

pytestmark = pytest.mark.django_db


def test_ingest_contract_creates_contract_row(tmp_path, capsys):
    sample_file = tmp_path / "sample_contract.txt"
    sample_file.write_text(
        "This Master Services Agreement sets out payment terms.", encoding="utf-8"
    )

    assert Contract.objects.count() == 0

    call_command(
        "ingest_contract",
        str(sample_file),
        "--engagement-id=ENG-CLI-001",
        "--razorpay-reference-type=payout",
        "--razorpay-reference-id=pout_CLI001",
    )

    assert Contract.objects.count() == 1
    contract = Contract.objects.get()
    assert contract.engagement_id == "ENG-CLI-001"
    assert contract.razorpay_reference_type == "payout"
    assert contract.razorpay_reference_id == "pout_CLI001"
    assert contract.raw_text == "This Master Services Agreement sets out payment terms."
    assert contract.source_filename == "sample_contract.txt"

    out = capsys.readouterr().out
    assert str(contract.id) in out


def test_ingest_contract_missing_file_raises_command_error():
    with pytest.raises(CommandError):
        call_command(
            "ingest_contract",
            "no_such_file.txt",
            "--engagement-id=ENG-CLI-002",
            "--razorpay-reference-type=payout",
            "--razorpay-reference-id=pout_CLI002",
        )

    assert Contract.objects.count() == 0


def test_ingest_contract_missing_razorpay_reference_id_raises_command_error(tmp_path):
    sample_file = tmp_path / "sample_contract.txt"
    sample_file.write_text("Some contract text.", encoding="utf-8")

    with pytest.raises(CommandError):
        call_command(
            "ingest_contract",
            str(sample_file),
            "--engagement-id=ENG-CLI-003",
            "--razorpay-reference-type=payout",
            "--razorpay-reference-id=",
        )

    assert Contract.objects.count() == 0
