"""DRF views for the `evaluation` app.

Follows `reporting/views.py`'s "every view is thin" convention: look up the
data through one selector, hand it to one serializer, return the Response -
no business logic lives here. `LatestEvalRunAPIView` is this app's first
(read-only) HTTP surface - everything else in `evaluation` is CLI-only
(`manage.py eval ...`, see `evaluation/management/commands/eval.py`).
"""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from evaluation import selectors as evaluation_selectors
from evaluation.serializers import EvalRunSerializer


class LatestEvalRunAPIView(APIView):
    """GET the most recently persisted `EvalRun`, wrapped as `{"eval_run": ...}`.

    `eval_run` is explicitly `null` (never an omitted key, and never a bare
    top-level `null` body - DRF's `JSONRenderer` renders a top-level `None`
    as an *empty* body with no `Content-Type`, which is indistinguishable
    from a broken response) when no `EvalRun` has ever been persisted (e.g.
    before `manage.py eval run` has been executed). That is an expected,
    valid state for a fresh project, not an error condition, so it is
    never a 404.
    """

    def get(self, request: Request) -> Response:
        eval_run = evaluation_selectors.get_latest_eval_run()
        if eval_run is None:
            return Response({"eval_run": None})
        serializer = EvalRunSerializer(instance=eval_run)
        return Response({"eval_run": serializer.data})
