"""URL routes for the `contracts` app.

See openspec/changes/add-contract-upload/design.md (Decisions -
"contracts/urls.py: path('contracts/create/', ...)").
"""

from django.urls import path

from contracts.views import ContractCreateAPIView

urlpatterns = [
    path(
        "contracts/create/",
        ContractCreateAPIView.as_view(),
        name="contract-create",
    ),
]
