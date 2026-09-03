"""URL routes for the `report_ui` app.

See design.md (add-report-ui) - "urls.py: contracts/<uuid:contract_id>/
report/, contracts/<uuid:contract_id>/audit-log/, and guardrail/, included
from the project's config/urls.py under a report/ prefix."
"""

from django.urls import path

from report_ui.views import (
    contract_audit_log_view,
    contract_report_view,
    guardrail_verification_view,
)

urlpatterns = [
    path(
        "contracts/<uuid:contract_id>/report/",
        contract_report_view,
        name="contract_report",
    ),
    path(
        "contracts/<uuid:contract_id>/audit-log/",
        contract_audit_log_view,
        name="contract_audit_log",
    ),
    path("guardrail/", guardrail_verification_view, name="guardrail_verification"),
]
