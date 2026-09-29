"""Domain enumerations.

These are the single source of truth for every categorical value in the system.
The database enum types, the Pydantic request/response models and the LLM
output schema are all derived from these, so there is exactly one place to add
a category.
"""
from __future__ import annotations

from enum import Enum


class Category(str, Enum):
    WATER = "water"
    ELECTRICITY = "electricity"
    SANITATION = "sanitation"
    ROADS = "roads"
    STREETLIGHTS = "streetlights"
    OTHER = "other"


class Priority(str, Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Status(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class TriagedBy(str, Enum):
    """How a complaint's classification was actually produced.

    Recorded per row so that ``/api/meta/providers`` can answer "what decided
    this?" without guessing from timestamps.
    """

    LLM_GROQ = "llm:groq"
    LLM_OLLAMA = "llm:ollama"
    RULES = "rules"
    RULES_FALLBACK = "rules:fallback"
    SIMULATED = "simulated"
