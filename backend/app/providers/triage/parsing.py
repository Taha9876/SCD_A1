"""Turn whatever the model actually said into a TriageResult, or fail loudly.

Every defence here exists because a model did this in testing at least once.
Nothing in this module ever calls eval, exec, or builds SQL.
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.providers.triage.base import TriageInvalidOutput, TriageResult

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def parse_triage_json(raw: str) -> TriageResult:
    """Parse and validate. Raises TriageInvalidOutput on anything unexpected."""
    if not raw or not raw.strip():
        raise TriageInvalidOutput("provider returned an empty body")

    candidate = raw.strip()

    # 1. Model wrapped the JSON in a markdown fence despite being told not to.
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    # 2. Model prefixed prose: "Sure! Here is the classification: {...}".
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            raise TriageInvalidOutput("no JSON object found in provider response")
        candidate = candidate[start : end + 1]

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise TriageInvalidOutput(f"provider response was not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise TriageInvalidOutput("provider response JSON was not an object")

    # 3. Cosmetic normalisation only -- never invent or coerce a value into the
    #    enum. An unknown category is an error, not an 'other'.
    for key in ("category", "priority"):
        value = payload.get(key)
        if isinstance(value, str):
            payload[key] = value.strip().lower()

    summary = payload.get("summary")
    if isinstance(summary, str):
        collapsed = " ".join(summary.split())
        # A model that ignores "one line" gets truncated rather than rejected:
        # the classification is still useful, the prose is not.
        payload["summary"] = collapsed[:140]

    try:
        return TriageResult.model_validate(payload)
    except ValidationError as exc:
        raise TriageInvalidOutput(
            f"provider response failed schema validation: {exc.error_count()} error(s)"
        ) from exc
