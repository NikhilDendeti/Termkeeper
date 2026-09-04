"""DRF serializers for the `contracts` app.

Only field declarations live here - all creation logic stays in
`contracts.services.create_contract`, which this serializer's validated_data
is passed to unmodified. See openspec/changes/add-contract-upload/design.md
(Decisions - "contracts app gains an HTTP surface").
"""

from __future__ import annotations

from rest_framework import serializers

from contracts.models import RazorpayReferenceType


class ContractCreateSerializer(serializers.Serializer):
    raw_text = serializers.CharField()
    engagement_id = serializers.CharField()
    razorpay_reference_type = serializers.ChoiceField(choices=RazorpayReferenceType.choices)
    razorpay_reference_id = serializers.CharField()
    source_filename = serializers.CharField(required=False, allow_null=True)
