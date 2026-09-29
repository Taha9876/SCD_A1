"""Deterministic keyword triage.

The floor of the system. It has no network, no key and no quota, so it cannot
fail -- which is what makes it usable as the fallback for everything else.
It is also the reference implementation of the contract: read this first.
"""
from __future__ import annotations

import re

from app.domain.enums import Category, Priority
from app.providers.triage.base import TriageResult

# Matching rules, learned the hard way -- see test_rules_matching_regressions:
#
#   - Keywords match WHOLE words (a trailing "s"/"es" plural is allowed), so
#     "week" no longer fires on "weekend", "meter" on "kilometer" or "tap" on
#     "tape". A keyword ending in "*" is a deliberate stem: "injur*" matches
#     injured, injury, injuries.
#   - Only the complaint TEXT is read, never the location. Almost every address
#     here contains "Road" ("Main Ferozepur Road"), which used to file a
#     noise complaint under roads -- the location says where, not what.
#
# Ordered most-specific first: "water main" should win over a bare "water".
_CATEGORY_KEYWORDS: list[tuple[Category, tuple[str, ...]]] = [
    # First, because it is the most specific: a tie between "street light"
    # and "electricity", or between "lamp post" and "road", is a streetlight
    # complaint. Ties go to the earlier entry.
    (
        Category.STREETLIGHTS,
        (
            "streetlight", "street light", "street lamp", "lamp post", "pole light",
            "dark street", "light not working", "lights off", "light",
        ),
    ),
    (
        Category.WATER,
        (
            "water main", "burst main", "water supply", "sewerage water", "pani",
            "water", "leak*", "tap", "pipeline", "pipe", "boring",
            "tanker", "water pressure",
        ),
    ),
    (
        Category.ELECTRICITY,
        (
            "load shedding", "loadshedding", "transformer", "electricity", "bijli",
            "power", "wapda", "k-electric", "voltage", "meter", "wire", "taar",
            "outage", "short circuit", "feeder",
        ),
    ),
    (
        Category.SANITATION,
        (
            "garbage", "kachra", "trash", "sewer*", "drain", "gutter",
            "sanitation", "waste", "dump", "manhole", "open drain", "stink", "smell",
        ),
    ),
    (
        Category.ROADS,
        (
            "pothole", "road", "sadak", "footpath", "pavement", "speed breaker",
            "manhole cover", "broken road", "encroachment", "traffic signal",
        ),
    ),
]

# Words that describe consequence, not subject. Urgency is about harm and scale.
_HIGH_PRIORITY = (
    "flood*", "electrocut*", "shock", "fire", "collaps*", "accident",
    "injur*", "child*", "bachay", "bachon", "hospital", "school",
    "sewage entering", "entering home*", "entering ground floor*", "no water for",
    "week", "emergenc*", "danger*", "khatra", "spark*", "live wire*",
    "overflow*", "burst*", "urgent*", "died", "death",
)
_LOW_PRIORITY = (
    "since yesterday only", "minor", "small", "cosmetic", "suggestion", "request for",
    "would be nice", "paint*", "sign board", "bench*",
)


def _pattern(keyword: str) -> re.Pattern[str]:
    """Whole-word match with an optional plural; a trailing * makes a stem."""
    if keyword.endswith("*"):
        return re.compile(r"\b" + re.escape(keyword[:-1]))
    return re.compile(r"\b" + re.escape(keyword) + r"(?:e?s)?\b")


# Compiled once at import: triage runs on every fallback and every seed row.
_CATEGORY_PATTERNS = [
    (category, [_pattern(k) for k in keywords]) for category, keywords in _CATEGORY_KEYWORDS
]
_HIGH_PATTERNS = [_pattern(k) for k in _HIGH_PRIORITY]
_LOW_PATTERNS = [_pattern(k) for k in _LOW_PRIORITY]


class RuleBasedTriage:
    """Always available, never raises."""

    name = "rules"

    async def triage(self, text: str, location: str) -> TriageResult:
        return self.triage_sync(text, location)

    def triage_sync(self, text: str, location: str) -> TriageResult:
        # The complaint text only. The location is used for the summary, never
        # for classification -- see the matching rules at the top of the file.
        haystack = " ".join(text.lower().split())

        category = Category.OTHER
        matched = 0
        for candidate, patterns in _CATEGORY_PATTERNS:
            hits = sum(1 for pattern in patterns if pattern.search(haystack))
            if hits > matched:
                category, matched = candidate, hits

        high_hits = sum(1 for pattern in _HIGH_PATTERNS if pattern.search(haystack))
        low_hits = sum(1 for pattern in _LOW_PATTERNS if pattern.search(haystack))
        if high_hits:
            priority = Priority.HIGH
        elif low_hits:
            priority = Priority.LOW
        else:
            priority = Priority.NORMAL

        # Confidence is a real signal here, not decoration: no keyword matched
        # means we genuinely do not know, and the dashboard should show that.
        confidence = 0.30 if matched == 0 else min(0.85, 0.45 + 0.12 * matched)

        return TriageResult(
            category=category,
            priority=priority,
            summary=_summarise(text, location, category),
            confidence=round(confidence, 2),
        )


def _summarise(text: str, location: str, category: Category) -> str:
    first = " ".join(text.split())
    if len(first) > 80:
        first = first[:77].rsplit(" ", 1)[0] + "..."
    summary = f"{category.value.title()} issue at {location}: {first}"
    return summary[:140]
