"""Template filters for the `report_ui` app.

Pure formatting only, no business logic - see design.md (add-report-ui) -
Decisions.
"""

from __future__ import annotations

import json
from typing import Any

from django import template

register = template.Library()


@register.filter(name="pretty_json")
def pretty_json(value: Any) -> str:
    """Format a JSON-serializable value with indentation, for readability.

    Used to render `AuditLogEntry.llm_response_raw` on the audit-log page -
    see specs/report-ui/audit-log-view/spec.md (Requirement: Raw model
    response inspectable per entry).
    """
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)
