"""Observability surface: which provider is deciding, and how it is doing."""
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SettingsDep, TriageServiceDep
from app.schemas import ProvidersOut, TriageRecordOut

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/providers", response_model=ProvidersOut)
async def providers(triage: TriageServiceDep, settings: SettingsDep) -> ProvidersOut:
    return ProvidersOut(
        active_provider=triage.provider_name,
        configured_provider=settings.triage_provider,
        triage_cache=triage.cache_stats(),
        recent=[TriageRecordOut.model_validate(record) for record in triage.recent()],
    )
