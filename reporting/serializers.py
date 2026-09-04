"""DRF serializers for the `reporting` app.

Every serializer here mirrors the plain-dict shape `reporting.selectors`
already produces - no business logic lives here, only field declarations.
See design.md (add-risk-scoring-report) - "New Django app: reporting".
"""

from __future__ import annotations

from rest_framework import serializers


class FlaggedClauseSerializer(serializers.Serializer):
    clause_id = serializers.UUIDField()
    sequence_index = serializers.IntegerField()
    clause_type = serializers.CharField(allow_null=True)
    clause_text = serializers.CharField()
    severity = serializers.CharField()
    asymmetry_score = serializers.FloatField()
    explanation = serializers.CharField()
    suggested_rewrite = serializers.CharField(allow_null=True)
    linked_mismatch_flag_ids = serializers.ListField(child=serializers.CharField())


class PlatformMismatchSerializer(serializers.Serializer):
    mismatch_id = serializers.UUIDField()
    mismatch_type = serializers.CharField()
    clause_id = serializers.UUIDField()
    sequence_index = serializers.IntegerField()
    expected_value = serializers.JSONField()
    actual_value = serializers.JSONField()
    description = serializers.CharField()


class NeedsHumanReviewClauseSerializer(serializers.Serializer):
    clause_id = serializers.UUIDField()
    sequence_index = serializers.IntegerField()
    clause_type = serializers.CharField(allow_null=True)
    clause_text = serializers.CharField()
    explanation = serializers.CharField()


class ContractReportSerializer(serializers.Serializer):
    contract_id = serializers.UUIDField()
    overall_risk_score = serializers.FloatField(allow_null=True)
    flagged_clauses = FlaggedClauseSerializer(many=True)
    platform_mismatches = PlatformMismatchSerializer(many=True)
    needs_human_review_clauses = NeedsHumanReviewClauseSerializer(many=True)
    severity_breakdown_by_clause_type = serializers.DictField(child=serializers.DictField())


class ContractDocumentSerializer(serializers.Serializer):
    contract_id = serializers.UUIDField()
    engagement_id = serializers.CharField()
    razorpay_reference_type = serializers.CharField()
    razorpay_reference_id = serializers.CharField()
    raw_text = serializers.CharField()
    source_filename = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    needs_human_review = serializers.BooleanField()
    human_review_reason = serializers.CharField(allow_null=True)


class AuditLogEntrySerializer(serializers.Serializer):
    """`prev_hash`/`entry_hash`/`chain_sequence` are additive, non-breaking
    fields for the per-Contract hash chain - `allow_null=True` because a
    pre-existing entry written before hash-chain verification existed is
    chain-exempt (all three null). See
    openspec/changes/add-audit-log-hash-chain/design.md.
    """

    id = serializers.UUIDField()
    contract_id = serializers.UUIDField()
    clause_id = serializers.UUIDField(allow_null=True)
    stage = serializers.IntegerField()
    prompt_version = serializers.CharField()
    llm_response_raw = serializers.JSONField()
    model_name = serializers.CharField()
    latency_ms = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    prev_hash = serializers.CharField(allow_null=True)
    entry_hash = serializers.CharField(allow_null=True)
    chain_sequence = serializers.IntegerField(allow_null=True)


# ---------------------------------------------------------------------------
# Contract summaries (spec: api/contract-listing)
# ---------------------------------------------------------------------------


class ContractSummarySerializer(serializers.Serializer):
    """Mirrors `reporting.selectors.ContractSummary` field-for-field."""

    contract_id = serializers.UUIDField()
    engagement_id = serializers.CharField()
    razorpay_reference_type = serializers.CharField()
    overall_risk_score = serializers.FloatField(allow_null=True)
    needs_human_review_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()


# ---------------------------------------------------------------------------
# Reasoning chain (spec: api/reasoning-chain)
# ---------------------------------------------------------------------------


class ExtractedTermSerializer(serializers.Serializer):
    """Mirrors `pipeline.models.ExtractedTerm` field-for-field."""

    id = serializers.UUIDField()
    term_type = serializers.CharField()
    value_raw = serializers.CharField()
    value_structured = serializers.JSONField()
    extraction_confidence = serializers.FloatField()
    needs_human_review = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class MismatchFlagSerializer(serializers.Serializer):
    """A clause's platform evidence, `PlatformMismatchSerializer`-shaped.

    Sources a raw `razorpay_integration.models.MismatchFlag` instance
    (unlike `PlatformMismatchSerializer`, which sources the plain-dict shape
    `get_contract_report`'s `_serialize_mismatch` already produces) - the
    field names and shape match so a frontend sees one consistent mismatch
    representation regardless of which endpoint it came from.
    """

    mismatch_id = serializers.UUIDField(source="id")
    mismatch_type = serializers.CharField()
    clause_id = serializers.SerializerMethodField()
    sequence_index = serializers.SerializerMethodField()
    expected_value = serializers.JSONField()
    actual_value = serializers.JSONField()
    description = serializers.CharField()

    def get_clause_id(self, obj):
        return obj.extracted_term.clause_id

    def get_sequence_index(self, obj):
        return obj.extracted_term.clause.sequence_index


class PlatformRecordSerializer(serializers.Serializer):
    """Mirrors `razorpay_integration.models.PlatformRecord` field-for-field.

    Used for `ClauseReasoningChainSerializer.verified_platform_records` - a
    clause's *confirmed* platform evidence (checked, no mismatch found),
    distinct from `MismatchFlagSerializer`'s flagged-deviation evidence. See
    specs/reporting/confirmed-platform-evidence/spec.md
    (add-confirmed-platform-evidence).
    """

    id = serializers.UUIDField()
    record_type = serializers.CharField()
    razorpay_id = serializers.CharField()
    payload = serializers.JSONField()
    razorpay_created_at = serializers.DateTimeField()


class RiskAssessmentSerializer(serializers.Serializer):
    """Mirrors `risk_scoring.models.RiskAssessment` field-for-field."""

    id = serializers.UUIDField()
    severity = serializers.CharField()
    asymmetry_score = serializers.FloatField()
    explanation = serializers.CharField()
    suggested_rewrite = serializers.CharField(allow_null=True)
    linked_mismatch_flag_ids = serializers.ListField(child=serializers.CharField())
    created_at = serializers.DateTimeField()


class ClauseReasoningChainSerializer(serializers.Serializer):
    """Mirrors `reporting.selectors.ClauseReasoningChain` field-for-field.

    Clause fields are flattened onto the top level (clause_id,
    sequence_index, clause_type, clause_text, ...) rather than nested under
    a `clause` key, matching the flattening convention already established
    by `FlaggedClauseSerializer`/`NeedsHumanReviewClauseSerializer` above.
    `extracted_terms`, `platform_evidence`, and `verified_platform_records`
    are always present, possibly empty, lists (never omitted or null -
    spec: api/reasoning-chain, "Clause with no platform evidence"; spec:
    reporting/confirmed-platform-evidence); `risk_assessment` is explicitly
    null when the clause has not yet been risk-scored (spec:
    api/reasoning-chain, "Clause not yet risk-scored") - DRF serializes a
    None attribute as null for a nested-serializer field automatically, no
    extra handling needed here.
    """

    clause_id = serializers.UUIDField(source="clause.id")
    sequence_index = serializers.IntegerField(source="clause.sequence_index")
    clause_type = serializers.CharField(source="clause.clause_type", allow_null=True)
    clause_text = serializers.CharField(source="clause.clause_text")
    classification_confidence = serializers.FloatField(
        source="clause.classification_confidence", allow_null=True
    )
    classification_rationale = serializers.CharField(
        source="clause.classification_rationale", allow_null=True
    )
    classification_needs_human_review = serializers.BooleanField()
    extracted_terms = ExtractedTermSerializer(many=True)
    platform_evidence = MismatchFlagSerializer(source="mismatch_flags", many=True)
    verified_platform_records = PlatformRecordSerializer(many=True)
    risk_assessment = RiskAssessmentSerializer()


# ---------------------------------------------------------------------------
# Guardrail verification (spec: api/guardrail-verification)
# ---------------------------------------------------------------------------


class GuardrailViolationSerializer(serializers.Serializer):
    """Mirrors `reporting.selectors.GuardrailViolation` field-for-field."""

    file = serializers.CharField()
    line = serializers.IntegerField()
    matched_call = serializers.CharField()


class GuardrailScanResultSerializer(serializers.Serializer):
    """Mirrors `reporting.selectors.GuardrailScanResult` field-for-field."""

    passed = serializers.BooleanField()
    scanned_files = serializers.ListField(child=serializers.CharField())
    violations = GuardrailViolationSerializer(many=True)
