"""Tests for reporting.selectors.scan_razorpay_guardrail (tasks 4.1-4.3, 4.6).

Spec: report-ui/guardrail-verification-view. `scan_razorpay_guardrail`
relocated from `report_ui.selectors` to `reporting.selectors` in
add-react-frontend - see that change's design.md. Import path updated only;
no behavior change.
"""

from __future__ import annotations

from pathlib import Path

from reporting.selectors import scan_razorpay_guardrail

_WRITE_CALL_SOURCE = '''
class Connector:
    def create_payout(self, sdk_client):
        return sdk_client.post("/v1/payouts", {"amount": 100})
'''

_READ_ONLY_SOURCE = '''
class Connector:
    def fetch_payouts(self, sdk_client):
        return sdk_client.get("/v1/payouts", {})

    def fetch_subscription(self, sdk_client, subscription_id):
        return sdk_client.subscription.fetch(subscription_id)
'''


def _write(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    return path


class TestWriteCallDetected:
    """Task 4.1: a `.post(` call is captured as a violation with file/line/call."""

    def test_post_call_is_flagged_with_correct_file_line_and_call(self, tmp_path):
        fixture_file = _write(tmp_path / "fixture_with_write.py", _WRITE_CALL_SOURCE)

        result = scan_razorpay_guardrail(scanned_paths=(fixture_file,), excluded_paths=())

        assert result.passed is False
        assert len(result.violations) == 1
        violation = result.violations[0]
        assert violation.file == str(fixture_file)
        assert violation.line == 4
        assert "post" in violation.matched_call


class TestCleanScanPasses:
    """Task 4.2: a file with only read calls yields passed=True and zero violations."""

    def test_read_only_file_passes_with_no_violations(self, tmp_path):
        fixture_file = _write(tmp_path / "fixture_read_only.py", _READ_ONLY_SOURCE)

        result = scan_razorpay_guardrail(scanned_paths=(fixture_file,), excluded_paths=())

        assert result.passed is True
        assert result.violations == []
        assert result.scanned_files == [str(fixture_file)]


class TestExcludedFixtureModuleNeverScanned:
    """Task 4.3: the excluded fixture/demo-seeding module is never in scanned_files."""

    def test_excluded_file_is_omitted_even_when_it_contains_write_calls(self, tmp_path):
        production_file = _write(tmp_path / "client.py", _READ_ONLY_SOURCE)
        fixture_module = _write(tmp_path / "fixtures.py", _WRITE_CALL_SOURCE)

        result = scan_razorpay_guardrail(
            scanned_paths=(production_file, fixture_module),
            excluded_paths=(fixture_module,),
        )

        assert str(fixture_module) not in result.scanned_files
        assert result.scanned_files == [str(production_file)]
        # The write call living only in the excluded file must not surface
        # as a violation either.
        assert result.passed is True
        assert result.violations == []


class TestScanIsLiveNotCached:
    """Task 4.6: a fixed violation no longer appears on the next scan."""

    def test_fixing_a_violation_and_rescanning_no_longer_reports_it(self, tmp_path):
        fixture_file = _write(tmp_path / "fixture.py", _WRITE_CALL_SOURCE)

        first_result = scan_razorpay_guardrail(scanned_paths=(fixture_file,), excluded_paths=())
        assert first_result.passed is False
        assert len(first_result.violations) == 1

        # Fix the violation in place.
        _write(fixture_file, _READ_ONLY_SOURCE)

        second_result = scan_razorpay_guardrail(scanned_paths=(fixture_file,), excluded_paths=())
        assert second_result.passed is True
        assert second_result.violations == []


class TestDefaultScanOfRealProductionFiles:
    """The real razorpay_integration production path passes the default scan."""

    def test_default_scan_passes_and_excludes_fixtures_module(self):
        result = scan_razorpay_guardrail()

        assert result.passed is True
        assert result.violations == []
        assert len(result.scanned_files) == 2
        assert not any(f.endswith("fixtures.py") for f in result.scanned_files)
        assert any(f.endswith("client.py") for f in result.scanned_files)
        assert any(f.endswith("services.py") for f in result.scanned_files)
