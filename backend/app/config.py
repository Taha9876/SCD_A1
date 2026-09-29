"""Application settings.

Everything that differs between a laptop, CI and a cluster is an environment
variable read here. Nothing in this file has a production credential as its
default -- a missing secret should fail loudly, not silently run with "changeme".
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["llm", "ollama", "rules", "simulated"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "civicpulse-backend"
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # --- Persistence -----------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://civicpulse:civicpulse@database:5432/civicpulse",
        description="SQLAlchemy async DSN. Never 'localhost' in a container.",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- Cache / rate limiting -------------------------------------------
    redis_url: str = Field(default="redis://cache:6379/0")
    stats_cache_ttl_seconds: int = 30
    triage_cache_ttl_seconds: int = 60 * 60 * 24  # 24h, per spec
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60

    # --- Triage ----------------------------------------------------------
    triage_provider: ProviderName = Field(default="rules")
    triage_timeout_seconds: float = 10.0
    triage_max_retries: int = 1

    llm_api_key: str = Field(default="", repr=False)
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "qwen/qwen3.8-27b"
    llm_provider_label: str = "groq"

    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:1b"

    simulated_failure_rate: float = 0.0
    simulated_seed: int = 1337

    # --- HTTP ------------------------------------------------------------
    cors_origins: str = Field(default="http://localhost:8080,http://localhost:5173")
    max_page_size: int = 100

    # --- Tracing (bonus) --------------------------------------------------
    # Empty disables tracing entirely: no exporter, no background thread, no
    # instrumentation. Set to the collector's OTLP/HTTP base URL, e.g.
    # http://jaeger:4318 -- a service name, never localhost.
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "civicpulse-backend"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def safe_dump(self) -> dict[str, object]:
        """Settings with every credential removed, safe to log at startup."""
        data = self.model_dump()
        data["llm_api_key"] = "***set***" if self.llm_api_key else "***unset***"
        data["database_url"] = _redact_dsn(self.database_url)
        data["redis_url"] = _redact_dsn(self.redis_url)
        return data


def _redact_dsn(dsn: str) -> str:
    """Strip user:password out of a DSN before it reaches a log line."""
    if "@" not in dsn:
        return dsn
    scheme, _, rest = dsn.partition("://")
    _, _, host = rest.partition("@")
    return f"{scheme}://***:***@{host}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
