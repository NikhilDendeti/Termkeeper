"""Shared LLM client wrapper.

Every model call in this project goes through `get_structured_completion` so
that structured-output enforcement and prompt-version tracking live in one
place instead of being duplicated per pipeline stage (see design.md for
`add-django-foundation`). `quote_is_verbatim` is the shared quote-grounding
validator reused by classification, extraction, and (from phase 3 onward)
risk scoring.

Implemented against the OpenAI Responses API's structured-outputs mode (see
design.md for `switch-llm-provider-to-openai` for the verified request/
response shape) - `client.responses.create(..., text={"format": {"type":
"json_schema", ...}})`, with the result parsed from the message's
`output_text` content item rather than free text.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)

# Name of the JSON-schema response format. Not user-facing - it only needs to
# be a valid, stable format name (see `ResponseFormatTextJSONSchemaConfigParam`).
_STRUCTURED_OUTPUT_SCHEMA_NAME = "structured_output"

# JSON Schema -> the Python type(s) that satisfy that JSON type, for the
# manual re-validation below. `bool` is deliberately excluded from the
# int/float checks: in Python `bool` is a subclass of `int`, and JSON Schema
# treats "integer"/"number" and "boolean" as disjoint types.
_JSON_TYPE_TO_PYTHON: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


class StructuredCompletionError(RuntimeError):
    """Raised when the model's response does not conform to the requested schema.

    Covers "the API returned an incomplete response" (e.g. hit
    max_output_tokens before finishing), "the model refused" (a `refusal`
    content item instead of `output_text`), "no message/output_text item was
    present at all", and "the output_text parsed but doesn't actually satisfy
    the given JSON schema" - the server-side `strict` json_schema enforcement
    should prevent the latter, but this wrapper never trusts that silently: a
    malformed response raises here rather than being handed back to the
    caller as if it were valid.
    """


def get_structured_completion(
    system_prompt: str,
    user_content: str,
    schema: dict[str, Any],
    *,
    prompt_version: str,
) -> dict[str, Any]:
    """Call the model and return a single JSON object conforming to `schema`.

    Forces the model to produce output matching `schema` via the Responses
    API's `text.format={"type": "json_schema", "schema": schema, "strict":
    True}`, so the result is parsed from a validated structured-output block
    rather than free text. Raises `StructuredCompletionError` if the response
    is incomplete, the model refused, or the parsed output does not conform
    to `schema`.

    `prompt_version` identifies the prompt/schema revision that produced the
    call, for traceability in logs and (by the caller) in the pipeline's
    `AuditLogEntry` - this wrapper does not persist anything itself.
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    started_at = time.monotonic()
    response = client.responses.create(
        model=settings.OPENAI_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": _STRUCTURED_OUTPUT_SCHEMA_NAME,
                "schema": schema,
                "strict": True,
            }
        },
    )
    latency_ms = int((time.monotonic() - started_at) * 1000)

    logger.info(
        "llm structured completion: prompt_version=%s model=%s latency_ms=%d",
        prompt_version,
        settings.OPENAI_MODEL,
        latency_ms,
    )

    if response.status == "incomplete":
        reason = getattr(response.incomplete_details, "reason", None)
        raise StructuredCompletionError(
            f"incomplete response for prompt_version={prompt_version!r}: "
            f"reason={reason!r}"
        )

    message_items = [item for item in response.output if item.type == "message"]
    if not message_items:
        raise StructuredCompletionError(
            f"expected a 'message' item in response.output for "
            f"prompt_version={prompt_version!r}, found none"
        )
    message = message_items[0]

    refusal_items = [item for item in message.content if item.type == "refusal"]
    if refusal_items:
        raise StructuredCompletionError(
            f"model refused for prompt_version={prompt_version!r}: "
            f"{refusal_items[0].refusal}"
        )

    output_text_items = [item for item in message.content if item.type == "output_text"]
    if not output_text_items:
        raise StructuredCompletionError(
            f"expected an 'output_text' item in the message content for "
            f"prompt_version={prompt_version!r}, found none"
        )

    try:
        result = json.loads(output_text_items[0].text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise StructuredCompletionError(
            f"could not parse output_text as JSON for prompt_version={prompt_version!r}: {exc}"
        ) from exc

    if not isinstance(result, dict):
        raise StructuredCompletionError(
            f"expected output_text JSON to be an object for "
            f"prompt_version={prompt_version!r}, got {type(result).__name__}"
        )

    # Defense in depth: `strict` asks the API to guarantee schema-conforming
    # output, but this wrapper never simply trusts that - re-validate the
    # returned object against the caller's schema before handing it back.
    _validate_against_schema(result, schema, path="$", prompt_version=prompt_version)

    return result


def _value_matches_json_type(value: Any, json_type: str) -> bool | None:
    """Whether `value` satisfies JSON Schema type keyword `json_type`.

    Returns `None` (rather than False) for an unrecognized type keyword, so
    callers can treat "unknown keyword" as "don't fail on this" instead of
    "always fails".
    """
    python_types = _JSON_TYPE_TO_PYTHON.get(json_type)
    if python_types is None:
        return None
    if isinstance(value, bool):
        # `bool` is a subclass of `int` in Python, but JSON Schema's
        # "integer"/"number" and "boolean" are disjoint types.
        return json_type == "boolean"
    return isinstance(value, python_types)


def _validate_against_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str,
    prompt_version: str,
) -> None:
    """Raise `StructuredCompletionError` unless `value` satisfies `schema`.

    A small, dependency-free subset of JSON Schema validation - object/array/
    string/integer/number/boolean/null types, `required`, `additionalProperties`,
    `enum`, and recursion into `properties`/`items`. This project has no
    `jsonschema` dependency, and the schemas passed to this function (fixed
    taxonomies, extracted-term shapes) don't need more than this subset.
    """

    def fail(message: str) -> None:
        raise StructuredCompletionError(
            f"schema validation failed at {path} for prompt_version={prompt_version!r}: "
            f"{message}"
        )

    json_type = schema.get("type")
    allowed_types = [json_type] if isinstance(json_type, str) else json_type
    if allowed_types:
        results = [_value_matches_json_type(value, t) for t in allowed_types]
        known_results = [r for r in results if r is not None]
        if known_results and not any(known_results):
            fail(f"expected type {json_type!r}, got {type(value).__name__}")

    if "enum" in schema and value not in schema["enum"]:
        fail(f"value {value!r} is not one of the allowed enum values {schema['enum']!r}")

    if isinstance(value, dict) and schema.get("type") == "object":
        properties = schema.get("properties", {})
        for required_key in schema.get("required", []):
            if required_key not in value:
                fail(f"missing required property {required_key!r}")
        if schema.get("additionalProperties") is False:
            extra_keys = sorted(set(value) - set(properties))
            if extra_keys:
                noun = "property" if len(extra_keys) == 1 else "properties"
                fail(f"unexpected {noun} {extra_keys!r}")
        for key, sub_schema in properties.items():
            if key in value:
                _validate_against_schema(
                    value[key],
                    sub_schema,
                    path=f"{path}.{key}",
                    prompt_version=prompt_version,
                )

    if isinstance(value, list) and schema.get("type") == "array":
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for index, item in enumerate(value):
                _validate_against_schema(
                    item,
                    items_schema,
                    path=f"{path}[{index}]",
                    prompt_version=prompt_version,
                )


_WHITESPACE_RUN = re.compile(r"\s+")


def _normalize_whitespace(text: str) -> str:
    """Collapse whitespace runs to one space and strip leading/trailing whitespace."""
    return _WHITESPACE_RUN.sub(" ", text).strip()


def quote_is_verbatim(source: str, quote: str) -> bool:
    """Return whether `quote` appears within `source`, ignoring whitespace formatting.

    A strict substring check on the actual words/characters - no fuzzy, semantic, or
    approximate matching, and a substituted, omitted, or added word still fails here.
    The one tolerance: runs of whitespace (spaces, tabs, newlines) in both `source` and
    `quote` are collapsed to a single space, and leading/trailing whitespace is stripped,
    before comparing - so line-wrapping and table-cell-extraction artifacts in a contract's
    raw_text (e.g. a payment-milestone table whose cells land on separate lines when copied
    into raw_text) don't cause a false verbatim-match failure. This is the shared grounding
    validator every pipeline stage uses to confirm a model-proposed span (a clause, an
    extracted value, a risk explanation's quote, a mismatch description's quote) is actually
    present in the source text rather than paraphrased or hallucinated.
    """
    return _normalize_whitespace(source).find(_normalize_whitespace(quote)) != -1
