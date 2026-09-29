"""LLMTriage and OllamaTriage over a mocked transport.

No network: httpx.MockTransport lets us assert on the exact request we send
and hand back the exact responses a real provider gives, including the ugly
ones. This is what makes "retry only on retryable errors" a tested claim
rather than a comment.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.domain.enums import Category, Priority
from app.providers.triage.base import (
    TriageBadRequest,
    TriageError,
    TriageInvalidOutput,
    TriageRateLimited,
    TriageTimeout,
    TriageUpstreamError,
)
from app.providers.triage.llm import LLMTriage
from app.providers.triage.ollama import OllamaTriage

GOOD_BODY = {
    "category": "water",
    "priority": "high",
    "summary": "Burst main flooding Street 12, water entering ground floors",
    "confidence": 0.93,
}
TEXT = "Burst water main flooding Street 12 since fajr, water entering ground floors."
LOCATION = "Street 12, G-9/4, Islamabad"


def _openai_envelope(content: str | dict) -> dict:
    if isinstance(content, dict):
        content = json.dumps(content)
    return {"choices": [{"message": {"content": content}}]}


def _llm(handler) -> LLMTriage:
    return LLMTriage(
        api_key="test-key",
        base_url="https://api.groq.com/openai/v1",
        model="qwen/qwen3.8-27b",
        timeout_seconds=5.0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


# --- Happy path and request shape ------------------------------------------


async def test_successful_call_returns_a_validated_result():
    provider = _llm(lambda request: httpx.Response(200, json=_openai_envelope(GOOD_BODY)))

    result = await provider.triage(TEXT, LOCATION)

    assert result.category is Category.WATER
    assert result.priority is Priority.HIGH
    assert result.confidence == pytest.approx(0.93)


async def test_request_carries_the_key_in_a_header_and_asks_for_json():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_openai_envelope(GOOD_BODY))

    await _llm(handler).triage(TEXT, LOCATION)

    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert body["response_format"] == {"type": "json_object"}
    # Temperature 0: triage is a classification, and a classifier that gives a
    # different answer to the same complaint each time is not a classifier.
    assert body["temperature"] == 0


async def test_complaint_text_is_sent_delimited_as_data():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_openai_envelope(GOOD_BODY))

    await _llm(handler).triage(TEXT, LOCATION)

    user_message = captured["body"]["messages"][1]["content"]
    assert "<complaint>" in user_message
    assert TEXT in user_message


# --- Error taxonomy: this is what drives the retry policy ------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, TriageRateLimited),
        (500, TriageUpstreamError),
        (502, TriageUpstreamError),
        (503, TriageUpstreamError),
        (400, TriageBadRequest),
        (401, TriageBadRequest),
        (404, TriageBadRequest),
    ],
)
async def test_http_status_maps_to_the_right_exception(status, expected):
    provider = _llm(lambda request: httpx.Response(status, json={"error": "nope"}))

    with pytest.raises(expected):
        await provider.triage(TEXT, LOCATION)


async def test_transport_timeout_becomes_triage_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(TriageTimeout):
        await _llm(handler).triage(TEXT, LOCATION)


async def test_connection_error_becomes_a_retryable_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(TriageUpstreamError):
        await _llm(handler).triage(TEXT, LOCATION)


# --- Bad output over a good connection -------------------------------------


async def test_prose_response_is_rejected_by_the_validator():
    provider = _llm(
        lambda request: httpx.Response(
            200, json=_openai_envelope("This looks like a water problem, fairly urgent.")
        )
    )

    with pytest.raises(TriageInvalidOutput):
        await provider.triage(TEXT, LOCATION)


async def test_invented_category_is_rejected_rather_than_coerced():
    """Silently mapping an unknown category to 'other' would hide a broken
    prompt and put a wrong row in the database."""
    provider = _llm(
        lambda request: httpx.Response(
            200, json=_openai_envelope({**GOOD_BODY, "category": "plumbing"})
        )
    )

    with pytest.raises(TriageInvalidOutput):
        await provider.triage(TEXT, LOCATION)


async def test_unexpected_envelope_is_an_error_not_a_crash():
    provider = _llm(lambda request: httpx.Response(200, json={"unexpected": "shape"}))

    with pytest.raises(TriageError, match="unexpected LLM envelope"):
        await provider.triage(TEXT, LOCATION)


def test_constructing_without_a_key_fails_immediately():
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        LLMTriage(api_key="", base_url="https://x", model="m", timeout_seconds=1.0)


# --- Ollama ----------------------------------------------------------------


async def test_ollama_sends_a_json_schema_and_parses_the_reply():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": json.dumps(GOOD_BODY)}})

    provider = OllamaTriage(
        base_url="http://ollama:11434",
        model="llama3.2:1b",
        timeout_seconds=5.0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await provider.triage(TEXT, LOCATION)

    assert result.category is Category.WATER
    # Ollama accepts a JSON Schema directly, which is a stronger constraint
    # than OpenAI's json_object mode.
    assert captured["body"]["format"]["properties"]["category"]["enum"] == [
        c.value for c in Category
    ]
    assert captured["body"]["stream"] is False


async def test_ollama_5xx_is_retryable():
    provider = OllamaTriage(
        base_url="http://ollama:11434",
        model="llama3.2:1b",
        timeout_seconds=5.0,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(503))
        ),
    )

    with pytest.raises(TriageUpstreamError):
        await provider.triage(TEXT, LOCATION)
