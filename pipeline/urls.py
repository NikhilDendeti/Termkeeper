"""URL routes for the `pipeline` app.

See openspec/changes/add-contract-upload/design.md (Decisions -
"pipeline/urls.py: path('contracts/<uuid:contract_id>/analyze/', ...)").
"""

from django.urls import path

from pipeline.views import AnalyzeContractAPIView

urlpatterns = [
    path(
        "contracts/<uuid:contract_id>/analyze/",
        AnalyzeContractAPIView.as_view(),
        name="contract-analyze",
    ),
]
