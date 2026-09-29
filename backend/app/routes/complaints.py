"""Complaint HTTP routes.

Parse, delegate, serialise, choose a status code. There is no SQL here, no
session, no triage policy and no copy of the state machine -- if any of those
appear in this file, the layering has been broken.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.dependencies import (
    ComplaintServiceDep,
    RateLimiterDep,
    SettingsDep,
    client_key,
)
from app.domain.enums import Category, Priority, Status
from app.domain.state_machine import InvalidTransition, allowed_transitions
from app.metrics import metrics
from app.models import Complaint
from app.schemas import (
    ComplaintCreate,
    ComplaintOut,
    ComplaintPage,
    ErrorOut,
    StatusUpdate,
)
from app.services.complaint_service import ComplaintNotFound

router = APIRouter(prefix="/api/complaints", tags=["complaints"])


def _to_out(row: Complaint) -> ComplaintOut:
    out = ComplaintOut.model_validate(row)
    out.allowed_transitions = allowed_transitions(Status(row.status))
    return out


@router.post(
    "",
    response_model=ComplaintOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorOut},
        429: {"model": ErrorOut, "description": "Rate limit exceeded"},
    },
)
async def create_complaint(
    payload: ComplaintCreate,
    request: Request,
    response: Response,
    service: ComplaintServiceDep,
    limiter: RateLimiterDep,
) -> ComplaintOut:
    decision = await limiter.check(client_key(request))
    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)

    if not decision.allowed:
        metrics.observe_rate_limited()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limited",
                "detail": (
                    f"Rate limit of {decision.limit} submissions per window exceeded. "
                    f"Retry in {decision.retry_after_seconds}s."
                ),
            },
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    row = await service.submit(payload)
    return _to_out(row)


@router.get("", response_model=ComplaintPage)
async def list_complaints(
    service: ComplaintServiceDep,
    settings: SettingsDep,
    category: Category | None = Query(default=None),
    priority: Priority | None = Query(default=None),
    status_filter: Status | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ComplaintPage:
    page_size = min(page_size, settings.max_page_size)
    result = await service.list(
        category=category,
        priority=priority,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    pages = (result.total + page_size - 1) // page_size if result.total else 0
    return ComplaintPage(
        items=[_to_out(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=pages,
    )


@router.get("/{complaint_id}", response_model=ComplaintOut, responses={404: {"model": ErrorOut}})
async def get_complaint(complaint_id: uuid.UUID, service: ComplaintServiceDep) -> ComplaintOut:
    try:
        row = await service.get(complaint_id)
    except ComplaintNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "detail": f"No complaint with id {complaint_id}."},
        ) from None
    return _to_out(row)


@router.patch(
    "/{complaint_id}/status",
    response_model=ComplaintOut,
    responses={404: {"model": ErrorOut}, 409: {"model": ErrorOut}},
)
async def update_status(
    complaint_id: uuid.UUID, payload: StatusUpdate, service: ComplaintServiceDep
) -> ComplaintOut:
    try:
        row = await service.change_status(complaint_id, payload.status)
    except ComplaintNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "detail": f"No complaint with id {complaint_id}."},
        ) from None
    except InvalidTransition as exc:
        # The 409 body names the attempted transition, because "error" is not
        # something an operator can act on and "open -> resolved is not
        # allowed; try in_progress" is.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "invalid_transition",
                "detail": str(exc),
                "current_status": exc.current.value,
                "attempted_status": exc.attempted.value,
                "allowed_transitions": [s.value for s in allowed_transitions(exc.current)],
            },
        ) from None
    return _to_out(row)
