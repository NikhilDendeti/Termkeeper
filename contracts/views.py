"""DRF views for the `contracts` app.

Thin per project convention: validate via the serializer, delegate all
creation logic to `contracts.services.create_contract`, translate its
`ValidationError` into a 400 response - no business logic here. See
openspec/changes/add-contract-upload/design.md (Decisions).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from contracts import services as contracts_services
from contracts.serializers import ContractCreateSerializer


class ContractCreateAPIView(APIView):
    """POST raw contract text plus engagement/Razorpay metadata to create a Contract.

    See specs/contracts/upload-api/spec.md (Requirement: Contract creation
    endpoint).
    """

    def post(self, request: Request) -> Response:
        serializer = ContractCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            contract = contracts_services.create_contract(**serializer.validated_data)
        except ValidationError as exc:
            errors = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        return Response({"contract_id": str(contract.id)}, status=status.HTTP_201_CREATED)
