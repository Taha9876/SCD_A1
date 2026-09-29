"""Hosted LLM triage over an OpenAI-compatible endpoint (Groq by default).

Uses httpx directly rather than the openai SDK so that the timeout, the error
taxonomy and the exact request body are all visible in this file -- the parts
the assignment is actually about are not hidden inside a client library.
Switching to another OpenAI-compatible host is a base_url change.
"""
from __future__ import annotations

import httpx

from app.providers.triage.base import (
    TriageBadRequest,
    TriageError,
    TriageRateLimited,
    TriageResult,
    TriageTimeout,
    TriageUpstreamError,
)
from app.providers.triage.parsing import parse_triage_json
from app.providers.triage.prompt import system_prompt, user_prompt


class LLMTriage:
    """The production path."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        label: str = "groq",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "LLM_API_KEY is empty. Set it in the environment (never in a file "
                "in the repository) or select a different TRIAGE_PROVIDER."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._client = client
        self.name = f"llm:{label}"

    async def triage(self, text: str, location: str) -> TriageResult:
        body = {
            "model": self._model,
            "temperature": 0,
            "max_tokens": 300,
            "messages": [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": user_prompt(text, location)},
            ],
            # Ask for structured output. We validate it anyway -- json_object
            # mode guarantees syntax, never semantics.
            "response_format": {"type": "json_object"},
        }

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        try:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=body,
                # The key goes in a header from the environment. It is never
                # logged: see app/logging_config.py, which redacts headers.
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise TriageTimeout(f"LLM call exceeded {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise TriageUpstreamError(f"transport error talking to LLM: {type(exc).__name__}") from exc
        finally:
            if owns_client:
                await client.aclose()

        _raise_for_status(response)

        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise TriageError(f"unexpected LLM envelope: {type(exc).__name__}") from exc

        return parse_triage_json(content)


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP status onto the retry policy.

    429 and 5xx are worth one more try. Any other 4xx means we sent something
    wrong; it will be equally wrong in 300ms, so it must not be retried.
    """
    if response.status_code == 429:
        raise TriageRateLimited("LLM provider returned 429")
    if response.status_code >= 500:
        raise TriageUpstreamError(f"LLM provider returned {response.status_code}")
    if response.status_code >= 400:
        raise TriageBadRequest(f"LLM provider returned {response.status_code}")


#: Exceptions worth exactly one retry. Everything else falls straight through
#: to the rule-based fallback.
RETRYABLE: tuple[type[Exception], ...] = (
    TriageTimeout,
    TriageRateLimited,
    TriageUpstreamError,
)
