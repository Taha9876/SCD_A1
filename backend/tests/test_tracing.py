"""Tracing: one trace from the browser's request, through the API, to the LLM.

The browser's fetch instrumentation sends a W3C `traceparent` header. These
tests send the same header by hand and assert that the server span, the triage
span and the outbound LLM request all land in that one trace, correctly nested.
"""
from __future__ import annotations

import json

import httpx
from fastapi import FastAPI
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from app.config import Settings
from app.providers.cache import InMemoryCache
from app.providers.triage.llm import LLMTriage
from app.services.triage_service import TriageService
from app.tracing import configure_tracing

# What the browser sends: version 00, a trace id, the browser span's id, sampled.
BROWSER_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
BROWSER_SPAN_ID = "00f067aa0ba902b7"
TRACEPARENT = f"00-{BROWSER_TRACE_ID}-{BROWSER_SPAN_ID}-01"


def test_tracing_is_off_unless_an_endpoint_is_configured():
    # The default for tests, CI and anyone who has not started a collector:
    # no provider, no exporter thread, no instrumentation.
    assert configure_tracing(FastAPI(), Settings(otel_exporter_otlp_endpoint="")) is None


async def test_one_trace_spans_browser_request_triage_and_llm_call(app, client, settings):
    exporter = InMemorySpanExporter()
    provider = configure_tracing(app, settings, exporter=exporter)
    assert provider is not None

    def fake_groq(request: httpx.Request) -> httpx.Response:
        # The trace continues across the process boundary to the provider too.
        assert request.headers["traceparent"].split("-")[1] == BROWSER_TRACE_ID
        content = {
            "category": "water",
            "priority": "high",
            "summary": "Burst main flooding Street 12",
            "confidence": 0.9,
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    llm_client = httpx.AsyncClient(transport=httpx.MockTransport(fake_groq))
    HTTPXClientInstrumentor.instrument_client(llm_client, tracer_provider=provider)
    app.state.triage_service = TriageService(
        provider=LLMTriage(
            api_key="test-key",
            base_url="https://api.groq.test/openai/v1",
            model="test-model",
            timeout_seconds=5,
            client=llm_client,
        ),
        cache=InMemoryCache(),
        settings=settings,
    )

    try:
        response = await client.post(
            "/api/complaints",
            json={
                "text": "Burst water main flooding Street 12, water entering ground floors.",
                "location": "Street 12, G-9/4, Islamabad",
            },
            headers={"traceparent": TRACEPARENT},
        )
        assert response.status_code == 201
        assert response.json()["triaged_by"] == "llm:groq"
        provider.force_flush()
    finally:
        HTTPXClientInstrumentor().uninstrument()
        await llm_client.aclose()

    spans = exporter.get_finished_spans()
    by_id = {s.context.span_id: s for s in spans}

    # Every span is in the browser's trace -- nothing started a new one.
    assert {format(s.context.trace_id, "032x") for s in spans} == {BROWSER_TRACE_ID}

    server = next(s for s in spans if s.kind is SpanKind.SERVER)
    assert format(server.parent.span_id, "016x") == BROWSER_SPAN_ID

    triage = next(s for s in spans if s.name == "triage")
    assert triage.attributes["triage.triaged_by"] == "llm:groq"
    assert triage.attributes["triage.fallback"] is False

    llm_call = next(s for s in spans if s.kind is SpanKind.CLIENT)
    assert llm_call.parent.span_id == triage.context.span_id

    # triage descends from the server span (possibly via ASGI send/receive spans).
    ancestor = by_id.get(triage.parent.span_id)
    while ancestor is not None and ancestor is not server:
        ancestor = by_id.get(ancestor.parent.span_id) if ancestor.parent else None
    assert ancestor is server
