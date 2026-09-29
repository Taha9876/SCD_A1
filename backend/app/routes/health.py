"""Liveness, readiness and metrics.

/health and /ready are separate because Kubernetes uses them for different
decisions, and wiring them backwards turns a slow database into a restart loop
across the whole Deployment:

  liveness  -> failing restarts the pod. It must therefore depend on nothing
               but this process. If it touched Postgres, a database blip would
               restart every backend pod simultaneously, and the restarts would
               make recovery slower rather than faster.
  readiness -> failing removes the pod from the Service endpoints. It SHOULD
               depend on Postgres and Redis, because a pod that cannot reach
               them cannot serve a request and should stop receiving traffic --
               without being killed, so it can rejoin when the dependency
               returns.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status

from app.config import get_settings
from app.dependencies import CacheDep, RepositoryDep
from app.metrics import metrics
from app.schemas import HealthOut, ReadyOut

logger = logging.getLogger("civicpulse.health")
router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Process is alive. Touches no dependency, by design."""
    return HealthOut(status="ok", service=get_settings().app_name)


@router.get("/ready", response_model=ReadyOut, responses={503: {"model": ReadyOut}})
async def ready(response: Response, repo: RepositoryDep, cache: CacheDep) -> ReadyOut:
    dependencies: dict[str, str] = {}

    try:
        await repo.ping()
        dependencies["database"] = "ok"
    except Exception as exc:
        dependencies["database"] = f"unavailable: {type(exc).__name__}"

    try:
        await cache.ping()
        dependencies["cache"] = "ok"
    except Exception as exc:
        dependencies["cache"] = f"unavailable: {type(exc).__name__}"

    failed = [name for name, state in dependencies.items() if state != "ok"]
    if failed:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning(
            "readiness check failed",
            extra={"event": "ready.fail", "failed_dependencies": failed},
        )
        return ReadyOut(status=f"not ready: {', '.join(failed)}", dependencies=dependencies)

    return ReadyOut(status="ready", dependencies=dependencies)


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")
