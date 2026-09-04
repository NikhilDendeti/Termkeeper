"""URL routes for the `evaluation` app.

Follows `reporting/urls.py`'s naming convention (a plain-English route
name matching the resource it exposes). `evaluation`'s only other
surface is CLI-only (`manage.py eval ...`), so this is its sole route.
"""

from django.urls import path

from evaluation.views import LatestEvalRunAPIView

urlpatterns = [
    path(
        "eval-runs/latest/",
        LatestEvalRunAPIView.as_view(),
        name="latest-eval-run",
    ),
]
