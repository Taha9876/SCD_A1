"""Fully offline triage against a local Ollama container.

Same interface, same validation, no key and no PII leaving the machine. It is
measurably slower and measurably worse at classification on a 1B model -- that
trade-off is the point, and the measurement is in docs/TRIAGE.md.
"""
from __future__ import annotations

import httpx

from app.providers.triage.base import (
    TriageError,
    TriageResult,
    TriageTimeout,
    TriageUpstreamError,
)
from app.providers.triage.parsing import parse_triage_json
from app.providers.triage.prompt import RESPONSE_SCHEMA, system_prompt, user_prompt


class OllamaTriage:
    name = "llm:ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._client = client

    async def triage(self, text: str, location: str) -> TriageResult:
        body = {
            "model": self._model,
            "stream": False,
            "options": {"temperature": 0},
            # Ollama takes a JSON Schema directly in `format`, which is a
            # stronger guarantee than OpenAI's json_object mode.
            "format": RESPONSE_SCHEMA,
            "messages": [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": user_prompt(text, location)},
            ],
        }

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        try:
            response = await client.post(
                f"{self._base_url}/api/chat", json=body, timeout=self._timeout
            )
        except httpx.TimeoutException as exc:
            raise TriageTimeout(f"Ollama call exceeded {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise TriageUpstreamError(f"transport error talking to Ollama: {type(exc).__name__}") from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code >= 500:
            raise TriageUpstreamError(f"Ollama returned {response.status_code}")
        if response.status_code >= 400:
            raise TriageError(f"Ollama returned {response.status_code}")

        try:
            content = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise TriageError(f"unexpected Ollama envelope: {type(exc).__name__}") from exc

        return parse_triage_json(content)
