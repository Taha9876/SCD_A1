"""Aggregate statistics route."""
from __future__ import annotations

from fastapi import APIRouter, Response

from app.dependencies import StatsServiceDep
from app.schemas import StatsOut

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats", response_model=StatsOut)
async def get_stats(response: Response, service: StatsServiceDep) -> StatsOut:
    payload = await service.get()
    # Surfaced as a header rather than in the body so the cache behaviour is
    # observable without changing the data contract -- and so the frontend can
    # render it, which is the thing the assignment asks for.
    response.headers["X-Cache"] = "HIT" if payload.cache_hit else "MISS"
    return StatsOut(
        total=payload.total,
        by_category=payload.by_category,
        by_priority=payload.by_priority,
        by_status=payload.by_status,
        generated_at=payload.generated_at,
    )
