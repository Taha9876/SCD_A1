"""Provider selection. The only place that knows which implementations exist.

Adding a provider means adding one branch here and one file next to it --
nothing in routes/, services/ or repositories/ changes. That is the
substitutability the assignment is testing.
"""
from __future__ import annotations

from app.config import Settings
from app.providers.triage.base import TriageProvider
from app.providers.triage.llm import LLMTriage
from app.providers.triage.ollama import OllamaTriage
from app.providers.triage.rules import RuleBasedTriage
from app.providers.triage.simulated import SimulatedTriage


def build_provider(settings: Settings) -> TriageProvider:
    match settings.triage_provider:
        case "llm":
            return LLMTriage(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                timeout_seconds=settings.triage_timeout_seconds,
                label=settings.llm_provider_label,
            )
        case "ollama":
            return OllamaTriage(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                timeout_seconds=settings.triage_timeout_seconds,
            )
        case "simulated":
            return SimulatedTriage(
                seed=settings.simulated_seed,
                failure_rate=settings.simulated_failure_rate,
            )
        case "rules":
            return RuleBasedTriage()
        case unknown:  # pragma: no cover - guarded by the Literal type
            raise ValueError(f"unknown TRIAGE_PROVIDER: {unknown!r}")
