"""Tests asserting `fixtures` is not reachable from the production cross-check path.

`razorpay_integration/fixtures.py` is the only place any write (POST/PUT/
PATCH/DELETE) call against Razorpay happens - see design.md
(add-razorpay-crosscheck) - "razorpay_integration/fixtures.py - the only
place writes happen." `services.py` (where `detect_mismatches` lives) and
`client.py` must never import it, directly or transitively.

Each dynamic check runs in a fresh subprocess/interpreter so nothing else
imported earlier in the test session could mask a real violation - if
`razorpay_integration.fixtures` were reachable from `services.py`'s import
graph, it would appear in `sys.modules` right after `import
razorpay_integration.services` alone, in a process where nothing else has
run yet.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys

import razorpay_integration.client as client_module
import razorpay_integration.services as services_module

_DJANGO_SETUP = (
    "import django, os\n"
    "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')\n"
    "django.setup()\n"
)


def _imports_fixtures_module(module) -> bool:
    """Whether `module`'s source contains any `import`/`from ... import` of
    `razorpay_integration.fixtures` - at module scope or inside a function
    body (a lazily-deferred import would still be a violation)."""
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[-1] == "fixtures" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name.split(".")[-1] == "fixtures":
                return True
            if any(alias.name == "fixtures" for alias in node.names):
                return True
    return False


def _assert_fixtures_not_imported_by(module_dotted_path: str) -> None:
    script = (
        _DJANGO_SETUP
        + "import sys\n"
        + f"import {module_dotted_path}\n"
        + "assert 'razorpay_integration.fixtures' not in sys.modules, ("
        + f"'{module_dotted_path} must never import razorpay_integration.fixtures, "
        + "even transitively')\n"
        + "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


class TestFixturesNotInProductionImportGraph:
    """Requirement: writes are confined to fixtures.py, never reachable from detect_mismatches."""

    def test_fixtures_module_not_reachable_by_importing_services(self):
        _assert_fixtures_not_imported_by("razorpay_integration.services")

    def test_fixtures_module_not_reachable_by_importing_client(self):
        _assert_fixtures_not_imported_by("razorpay_integration.client")

    def test_services_source_contains_no_import_of_fixtures(self):
        assert _imports_fixtures_module(services_module) is False

    def test_client_source_contains_no_import_of_fixtures(self):
        assert _imports_fixtures_module(client_module) is False
