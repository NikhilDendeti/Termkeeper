"""DRF serializers for the `evaluation` app.

Mirrors `reporting/serializers.py`'s convention: every serializer here
mirrors the source (a Django model instance, for `EvalRunSerializer`)
field-for-field - no business logic lives here, only field declarations.
"""

from __future__ import annotations

from rest_framework import serializers


class EvalRunSerializer(serializers.Serializer):
    """Mirrors `evaluation.models.EvalRun` field-for-field.

    `precision_recall_f1` and `cost_report` are opaque JSON blobs already
    shaped by `evaluation.dataset_types`' `as_dict()` methods (see
    `evaluation.services.run_eval`) - passed through as-is via
    `JSONField()` rather than re-declared field-by-field here.
    """

    id = serializers.UUIDField()
    run_at = serializers.DateTimeField()
    dataset_version = serializers.CharField()
    fixture_version = serializers.CharField()
    precision_recall_f1 = serializers.JSONField()
    severity_calibration_score = serializers.FloatField()
    cost_report = serializers.JSONField()
    false_positive_cost_note = serializers.CharField()
    pipeline_version = serializers.CharField()
    prompt_version = serializers.CharField()
