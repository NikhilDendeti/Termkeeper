"""Tests for core.llm_client.

Every `openai.OpenAI()` call is mocked - this module makes no real
network call, per project convention.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.llm_client import (
    StructuredCompletionError,
    get_structured_completion,
    quote_is_verbatim,
)

CLAUSE_TYPE_SCHEMA = {
    "type": "object",
    "properties": {
        "clause_type": {
            "type": "string",
            "enum": ["payment_schedule", "termination"],
        },
        "confidence": {"type": "number"},
    },
    "required": ["clause_type", "confidence"],
    "additionalProperties": False,
}


def _output_text_item(payload):
    item = MagicMock()
    item.type = "output_text"
    item.text = json.dumps(payload)
    return item


def _refusal_item(reason):
    item = MagicMock()
    item.type = "refusal"
    item.refusal = reason
    return item


def _message_item(*, content_items):
    item = MagicMock()
    item.type = "message"
    item.content = content_items
    return item


def _mock_response(
    *,
    status="completed",
    tool_input=None,
    include_message=True,
    extra_output_items=None,
    content_items=None,
    incomplete_reason=None,
):
    """Build a MagicMock standing in for an `openai.types.responses.Response`.

    Only the attributes `core.llm_client.get_structured_completion` reads
    (`status`, `incomplete_details.reason`, `output[*].type/.content`,
    content item `.type`/`.text`/`.refusal`) are set - a full pydantic
    `Response` isn't needed to exercise this code.
    """
    output_items = list(extra_output_items or [])
    if include_message:
        if content_items is None:
            content_items = [_output_text_item(tool_input)]
        output_items.append(_message_item(content_items=content_items))

    response = MagicMock()
    response.status = status
    response.incomplete_details = MagicMock()
    response.incomplete_details.reason = incomplete_reason
    response.output = output_items
    return response


class TestGetStructuredCompletion:
    @patch("core.llm_client.OpenAI")
    def test_returns_schema_conforming_output(self, mock_openai_cls):
        mock_client = mock_openai_cls.return_value
        valid_input = {"clause_type": "payment_schedule", "confidence": 0.92}
        mock_client.responses.create.return_value = _mock_response(tool_input=valid_input)

        result = get_structured_completion(
            "system prompt", "user content", CLAUSE_TYPE_SCHEMA, prompt_version="clause-type-v1"
        )

        assert result == valid_input

    @patch("core.llm_client.OpenAI")
    def test_forces_json_schema_strict_output_format(self, mock_openai_cls):
        """The call must force json_schema structured output, not leave the model
        free to reply in text.
        """
        mock_client = mock_openai_cls.return_value
        valid_input = {"clause_type": "payment_schedule", "confidence": 0.92}
        mock_client.responses.create.return_value = _mock_response(tool_input=valid_input)

        get_structured_completion(
            "system prompt", "user content", CLAUSE_TYPE_SCHEMA, prompt_version="clause-type-v1"
        )

        _, kwargs = mock_client.responses.create.call_args
        text_format = kwargs["text"]["format"]
        assert text_format["type"] == "json_schema"
        assert text_format["schema"] == CLAUSE_TYPE_SCHEMA
        assert text_format["strict"] is True
        assert kwargs["input"] == [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "user content"},
        ]

    @patch("core.llm_client.OpenAI")
    def test_raises_when_response_is_incomplete(self, mock_openai_cls):
        """A response cut off before finishing (e.g. hit max_output_tokens) must
        raise, not return silently.
        """
        mock_client = mock_openai_cls.return_value
        mock_client.responses.create.return_value = _mock_response(
            status="incomplete", include_message=False, incomplete_reason="max_output_tokens"
        )

        with pytest.raises(StructuredCompletionError):
            get_structured_completion(
                "system", "user", CLAUSE_TYPE_SCHEMA, prompt_version="clause-type-v1"
            )

    @patch("core.llm_client.OpenAI")
    def test_raises_when_no_message_item_present(self, mock_openai_cls):
        mock_client = mock_openai_cls.return_value
        mock_client.responses.create.return_value = _mock_response(include_message=False)

        with pytest.raises(StructuredCompletionError):
            get_structured_completion(
                "system", "user", CLAUSE_TYPE_SCHEMA, prompt_version="clause-type-v1"
            )

    @patch("core.llm_client.OpenAI")
    def test_raises_when_model_refuses(self, mock_openai_cls):
        mock_client = mock_openai_cls.return_value
        mock_client.responses.create.return_value = _mock_response(
            content_items=[_refusal_item("I cannot classify this clause.")]
        )

        with pytest.raises(StructuredCompletionError):
            get_structured_completion(
                "system", "user", CLAUSE_TYPE_SCHEMA, prompt_version="clause-type-v1"
            )

    @patch("core.llm_client.OpenAI")
    def test_raises_when_required_field_is_missing(self, mock_openai_cls):
        mock_client = mock_openai_cls.return_value
        mock_client.responses.create.return_value = _mock_response(
            tool_input={"clause_type": "payment_schedule"}  # "confidence" missing
        )

        with pytest.raises(StructuredCompletionError):
            get_structured_completion(
                "system", "user", CLAUSE_TYPE_SCHEMA, prompt_version="clause-type-v1"
            )

    @patch("core.llm_client.OpenAI")
    def test_raises_when_value_is_outside_the_fixed_taxonomy(self, mock_openai_cls):
        mock_client = mock_openai_cls.return_value
        mock_client.responses.create.return_value = _mock_response(
            tool_input={"clause_type": "not_a_real_clause_type", "confidence": 0.8}
        )

        with pytest.raises(StructuredCompletionError):
            get_structured_completion(
                "system", "user", CLAUSE_TYPE_SCHEMA, prompt_version="clause-type-v1"
            )

    @patch("core.llm_client.OpenAI")
    def test_raises_when_field_has_the_wrong_type(self, mock_openai_cls):
        mock_client = mock_openai_cls.return_value
        mock_client.responses.create.return_value = _mock_response(
            tool_input={"clause_type": "payment_schedule", "confidence": "very confident"}
        )

        with pytest.raises(StructuredCompletionError):
            get_structured_completion(
                "system", "user", CLAUSE_TYPE_SCHEMA, prompt_version="clause-type-v1"
            )

    @patch("core.llm_client.OpenAI")
    def test_raises_on_unexpected_additional_property(self, mock_openai_cls):
        mock_client = mock_openai_cls.return_value
        mock_client.responses.create.return_value = _mock_response(
            tool_input={
                "clause_type": "payment_schedule",
                "confidence": 0.8,
                "unexpected_field": "surprise",
            }
        )

        with pytest.raises(StructuredCompletionError):
            get_structured_completion(
                "system", "user", CLAUSE_TYPE_SCHEMA, prompt_version="clause-type-v1"
            )


class TestQuoteIsVerbatim:
    def test_exact_match_quote_is_verbatim(self):
        source = "Payment shall be made net 30 days from the invoice date."
        quote = "net 30 days from the invoice date"

        assert quote_is_verbatim(source, quote) is True

    def test_paraphrased_quote_is_not_verbatim(self):
        source = "Payment shall be made net 30 days from the invoice date."
        quote = "Payment is due within thirty days of invoicing"

        assert quote_is_verbatim(source, quote) is False

    def test_quote_with_trailing_whitespace_difference_is_not_verbatim(self):
        source = "Payment shall be made net 30 days from the invoice date."
        # Same text but with an extra trailing space that isn't in the source -
        # verbatim means character-for-character, so this must fail too.
        quote = "net 30 days from the invoice date. "

        assert quote_is_verbatim(source, quote) is False
