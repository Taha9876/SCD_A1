"""FastAPI application factory and process lifecycle.

Two things here are worth reading closely: the lifespan handler, which is what
makes a rolling update lossless, and the exception handlers, which are what
make every non-2xx body in the system the same shape.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import dispose_engine
from app.logging_config import configure_logging
from app.middleware import RequestContextMiddleware, ShutdownState
from app.providers.cache import RedisCache
from app.providers.triage.factory import build_provider
from app.routes import complaints, health, meta, stats
from app.services.triage_service import TriageService
from app.tracing import configure_tracing

logger = logging.getLogger("civicpulse.app")

#: How long we let in-flight requests finish after SIGTERM. Must be comfortably
#: below the Kubernetes terminationGracePeriodSeconds (30 in k8s/base/backend
#: .yaml), or the kubelet SIGKILLs us mid-drain and the drain was pointless.
DRAIN_TIMEOUT_SECONDS = 20.0


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    shutdown = ShutdownState()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.cache = RedisCache(settings.redis_url)
        app.state.triage_service = TriageService(
            provider=build_provider(settings),
            cache=app.state.cache,
            settings=settings,
        )
        app.state.shutdown = shutdown
        logger.info(
            "startup complete",
            extra={"event": "app.startup", "settings": settings.safe_dump()},
        )

        yield

        # --- SIGTERM path ------------------------------------------------
        # uvicorn turns SIGTERM into shutdown, which runs this. We stop
        # accepting new work, let what is already running finish, then close
        # the pools. Without this, every rolling update drops the requests
        # that were in flight when the pod was told to go.
        shutdown.draining = True
        logger.info(
            "draining",
            extra={"event": "app.drain_start", "in_flight": shutdown.in_flight},
        )
        drained = await shutdown.wait_for_idle(DRAIN_TIMEOUT_SECONDS)
        if not drained:
            logger.warning(
                "drain timed out with requests still in flight",
                extra={"event": "app.drain_timeout", "in_flight": shutdown.in_flight},
            )

        await dispose_engine()
        with suppress(Exception):
            await app.state.cache.close()
        logger.info("shutdown complete", extra={"event": "app.shutdown"})

    app = FastAPI(
        title="CivicPulse API",
        version="1.0.0",
        description=(
            "Municipal complaint intake, triage and operations. "
            "The OpenAPI schema served at /openapi.json is the contract the "
            "frontend client is typed against."
        ),
        lifespan=lifespan,
    )

    # Explicit origins, never "*": credentials plus a wildcard is a same-origin
    # policy with the safety catch filed off.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        # traceparent/tracestate: the browser's trace context (bonus tracing),
        # needed only when API_BASE_URL makes the API cross-origin.
        allow_headers=["Content-Type", "X-Request-ID", "traceparent", "tracestate"],
        expose_headers=["X-Cache", "X-Request-ID", "Retry-After",
                        "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )
    app.add_middleware(RequestContextMiddleware, shutdown=shutdown)

    app.include_router(complaints.router)
    app.include_router(stats.router)
    app.include_router(meta.router)
    app.include_router(health.router)

    _install_error_handlers(app)
    configure_tracing(app, settings)
    return app


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        """Field-level errors, because "400 Bad Request" does not tell a
        citizen which box to fix."""
        fields = []
        for error in exc.errors():
            location = [str(part) for part in error["loc"] if part != "body"]
            fields.append(
                {
                    "field": ".".join(location) or "body",
                    "message": error["msg"],
                    "type": error["type"],
                }
            )
        return JSONResponse(
            status_code=400,
            content={
                "error": "validation_error",
                "detail": "One or more fields are invalid.",
                "fields": fields,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        # Routes raise HTTPException with a dict detail so they can attach
        # domain context (attempted transition, retry-after). Strings from
        # framework-raised exceptions are normalised into the same shape.
        if isinstance(exc.detail, dict):
            body = dict(exc.detail)
            body.setdefault("error", "error")
            body.setdefault("detail", "")
        else:
            body = {"error": _slug(exc.status_code), "detail": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("unhandled exception", extra={"event": "app.unhandled"})
        # Never leak the exception text to a citizen: it is the fastest route
        # from a stack trace to a DSN in someone's browser tab.
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": "An unexpected error occurred. The incident has been logged.",
            },
        )


def _slug(status_code: int) -> str:
    return {
        400: "bad_request",
        404: "not_found",
        409: "conflict",
        429: "rate_limited",
        503: "unavailable",
    }.get(status_code, "error")


app = create_app()
