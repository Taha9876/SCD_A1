"""Cross-cutting HTTP concerns: request id, access log, metrics, drain.

The drain counter is the half of graceful shutdown that lives in the request
path: it is what lets the lifespan handler wait for in-flight work instead of
guessing with a sleep.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.logging_config import request_id_var
from app.metrics import metrics

logger = logging.getLogger("civicpulse.http")


class ShutdownState:
    """Shared between the middleware and the lifespan handler."""

    def __init__(self) -> None:
        self.draining = False
        self.in_flight = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def enter(self) -> None:
        self.in_flight += 1
        self._idle.clear()

    def exit(self) -> None:
        self.in_flight = max(0, self.in_flight - 1)
        if self.in_flight == 0:
            self._idle.set()

    async def wait_for_idle(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._idle.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, shutdown: ShutdownState) -> None:
        super().__init__(app)
        self._shutdown = shutdown

    async def dispatch(self, request: Request, call_next):
        # Propagate the caller's id if there is one so a trace survives the
        # hop from nginx; mint one otherwise so there is never a line without.
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(request_id)

        if self._shutdown.draining:
            # Already draining: refuse new work politely rather than accepting
            # a request we have promised the orchestrator we will not finish.
            return JSONResponse(
                {"error": "shutting_down", "detail": "server is draining, retry"},
                status_code=503,
                headers={"Retry-After": "1", "X-Request-ID": request_id},
            )

        self._shutdown.enter()
        started = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            elapsed = time.perf_counter() - started
            route = _route_template(request)
            metrics.observe_request(request.method, route, 500, elapsed)
            logger.exception(
                "unhandled error",
                extra={"event": "http.error", "method": request.method, "path": route},
            )
            raise
        finally:
            self._shutdown.exit()
            request_id_var.reset(token)

        elapsed = time.perf_counter() - started
        route = _route_template(request)
        metrics.observe_request(request.method, route, response.status_code, elapsed)
        response.headers["X-Request-ID"] = request_id

        # /health and /ready are polled every couple of seconds by kubelet.
        # Logging them at INFO buries every real line in probe noise.
        level = logging.DEBUG if request.url.path in ("/health", "/ready", "/metrics") else logging.INFO
        logger.log(
            level,
            "request completed",
            extra={
                "event": "http.access",
                "method": request.method,
                "path": route,
                "status": response.status_code,
                "duration_ms": round(elapsed * 1000, 2),
            },
        )
        return response


def _route_template(request: Request) -> str:
    """Use the route pattern, not the raw path.

    Otherwise every UUID becomes its own metric label value and the time series
    cardinality grows without bound -- the classic way to take out Prometheus.
    """
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)
