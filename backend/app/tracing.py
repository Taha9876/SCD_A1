"""OpenTelemetry tracing: one trace from the browser, through the API, to the LLM.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set. When it is:

  * FastAPI instrumentation opens a server span per request and continues the
    trace the browser started, via the W3C `traceparent` header the frontend's
    fetch instrumentation attaches (frontend/src/tracing.ts).
  * TriageService opens a "triage" span around the whole decision.
  * httpx instrumentation opens a client span for the outbound call to the
    provider -- api.groq.com, or ollama -- as a child of that triage span.

So a slow complaint submission can be read off one waterfall: how much of it
was the browser, the database, the cache lookup, and the model.

Health, readiness and metrics are excluded: the kubelet and Prometheus poll
them every few seconds, and tracing them would bury every real request.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from app.config import Settings

logger = logging.getLogger("civicpulse.tracing")

EXCLUDED_URLS = "health,ready,metrics"


def configure_tracing(
    app: FastAPI, settings: Settings, *, exporter: SpanExporter | None = None
) -> TracerProvider | None:
    """Install tracing on `app`. Returns the provider, or None when disabled.

    `exporter` exists for tests, which pass an in-memory one; everything else
    exports over OTLP/HTTP to the configured collector.
    """
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
    if not endpoint and exporter is None:
        return None

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment.name": settings.environment,
            }
        )
    )
    # Batch, not simple: export happens on a background thread, so a slow or
    # absent collector can never add latency to a citizen's request.
    provider.add_span_processor(
        BatchSpanProcessor(exporter or OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, excluded_urls=EXCLUDED_URLS
    )
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)

    logger.info(
        "tracing enabled",
        extra={"event": "tracing.enabled", "endpoint": endpoint or "<in-memory>"},
    )
    return provider
