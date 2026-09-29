"""State machine unit tests, provider selection, and the observability route."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.enums import Category, Priority, Status
from app.domain.state_machine import (
    TERMINAL_STATUSES,
    TRANSITIONS,
    InvalidTransition,
    allowed_transitions,
    assert_transition,
    can_transition,
)
from app.providers.triage.base import TriageUpstreamError
from app.providers.triage.factory import build_provider
from app.providers.triage.rules import RuleBasedTriage
from app.providers.triage.simulated import SimulatedTriage

# --- State machine ---------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "attempted"),
    [
        (Status.OPEN, Status.IN_PROGRESS),
        (Status.OPEN, Status.REJECTED),
        (Status.IN_PROGRESS, Status.RESOLVED),
        (Status.IN_PROGRESS, Status.REJECTED),
    ],
)
def test_legal_transitions(current, attempted):
    assert can_transition(current, attempted)
    assert_transition(current, attempted)  # must not raise


@pytest.mark.parametrize(
    ("current", "attempted"),
    [
        (Status.OPEN, Status.RESOLVED),       # cannot skip in_progress
        (Status.OPEN, Status.OPEN),           # no self-transition
        (Status.RESOLVED, Status.OPEN),       # terminal
        (Status.RESOLVED, Status.IN_PROGRESS),
        (Status.REJECTED, Status.OPEN),
        (Status.IN_PROGRESS, Status.OPEN),    # no going back
    ],
)
def test_illegal_transitions_raise_with_both_endpoints_named(current, attempted):
    with pytest.raises(InvalidTransition) as exc_info:
        assert_transition(current, attempted)

    error = exc_info.value
    assert error.current is current
    assert error.attempted is attempted
    assert f"{current.value} -> {attempted.value}" in str(error)


def test_every_status_appears_in_the_transition_table():
    """A status added to the enum but not to the table would raise KeyError at
    runtime instead of returning a clean 409."""
    assert set(TRANSITIONS) == set(Status)


def test_terminal_statuses_are_exactly_resolved_and_rejected():
    assert frozenset({Status.RESOLVED, Status.REJECTED}) == TERMINAL_STATUSES


def test_allowed_transitions_is_sorted_for_a_stable_api_response():
    assert allowed_transitions(Status.OPEN) == [Status.IN_PROGRESS, Status.REJECTED]
    assert allowed_transitions(Status.RESOLVED) == []


# --- Rule-based triage -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Burst water main flooding the street, pani everywhere", Category.WATER),
        ("Transformer sparking and load shedding for 14 hours", Category.ELECTRICITY),
        ("Garbage not lifted, kachra spreading and gutter overflowing", Category.SANITATION),
        ("Big pothole in the road caused a motorcycle accident", Category.ROADS),
        ("Street lights of our lane are not working since last month", Category.STREETLIGHTS),
        ("The marriage hall next door plays loud music till 2am", Category.OTHER),
    ],
)
def test_rules_classify_by_subject(text, expected):
    result = RuleBasedTriage().triage_sync(text, "Somewhere, Lahore")
    assert result.category is expected


def test_rules_escalate_on_consequence_not_subject():
    """Urgency is about harm and scale, not about which department owns it."""
    urgent = RuleBasedTriage().triage_sync(
        "Water is flooding and entering ground floors, a child was injured", "Street 12"
    )
    routine = RuleBasedTriage().triage_sync(
        "Water pressure is a bit low on the first floor", "Street 12"
    )

    assert urgent.priority is Priority.HIGH
    assert routine.priority is Priority.NORMAL


def test_rules_report_low_confidence_when_nothing_matches():
    result = RuleBasedTriage().triage_sync("Something is wrong here please help", "Lahore")

    assert result.category is Category.OTHER
    assert result.confidence < 0.4  # honest uncertainty, surfaced to the dashboard


def test_rules_summary_respects_the_140_character_limit():
    result = RuleBasedTriage().triage_sync("water leak " * 60, "A very long location name here")
    assert len(result.summary) <= 140


# --- Determinism -----------------------------------------------------------


async def test_simulated_provider_is_deterministic():
    """The reason CI can be green on every run without a retry loop."""
    a = SimulatedTriage(seed=1337)
    b = SimulatedTriage(seed=1337)

    first = await a.triage("Burst water main flooding the street", "Street 12")
    second = await b.triage("Burst water main flooding the street", "Street 12")

    assert first.model_dump() == second.model_dump()


async def test_simulated_failure_injection_is_deterministic_per_input():
    provider = SimulatedTriage(seed=1337, failure_rate=1.0)

    with pytest.raises(TriageUpstreamError, match="injected"):
        await provider.triage("anything at all here", "Street 12")


# --- Provider factory ------------------------------------------------------


def _settings(**overrides) -> Settings:
    base = {"database_url": "sqlite+aiosqlite:///:memory:", "redis_url": "redis://unused"}
    base.update(overrides)
    return Settings(**base)


@pytest.mark.parametrize(
    ("configured", "expected_name"),
    [
        ("rules", "rules"),
        ("simulated", "simulated"),
        ("ollama", "llm:ollama"),
    ],
)
def test_factory_selects_provider_by_environment_variable(configured, expected_name):
    provider = build_provider(_settings(triage_provider=configured))
    assert provider.name == expected_name


def test_llm_provider_selected_and_labelled():
    provider = build_provider(
        _settings(triage_provider="llm", llm_api_key="test-key", llm_provider_label="groq")
    )
    assert provider.name == "llm:groq"


def test_llm_provider_refuses_to_start_without_a_key():
    """Failing loudly beats running with an empty Authorization header and
    discovering it as a 401 in front of a citizen."""
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        build_provider(_settings(triage_provider="llm", llm_api_key=""))


# --- /api/meta/providers ---------------------------------------------------


async def test_providers_endpoint_reports_the_active_provider(client):
    response = await client.get("/api/meta/providers")

    assert response.status_code == 200
    assert response.json()["active_provider"] == "simulated"


async def test_providers_endpoint_records_recent_outcomes(client, valid_complaint):
    await client.post("/api/complaints", json=valid_complaint)

    body = (await client.get("/api/meta/providers")).json()

    assert len(body["recent"]) >= 1
    record = body["recent"][0]
    assert record["provider"] == "simulated"
    assert record["fallback"] is False
    assert record["latency_ms"] >= 0
    assert record["category"] == "water"


async def test_providers_endpoint_reports_measured_cache_hit_rate(client, valid_complaint):
    await client.post("/api/complaints", json=valid_complaint)
    await client.post("/api/complaints", json=valid_complaint)

    body = (await client.get("/api/meta/providers")).json()

    assert body["triage_cache"]["lookups"] == 2
    assert body["triage_cache"]["hits"] == 1
    assert body["triage_cache"]["hit_rate"] == 0.5


async def test_recent_outcomes_are_capped_at_twenty(triage_service):
    """An unbounded observability buffer is a memory leak with good intentions."""
    for i in range(25):
        await triage_service.triage(f"Pothole number {i} on the main road here", "Lahore")

    assert len(triage_service.recent()) == 20


# --- Settings --------------------------------------------------------------


def test_safe_dump_never_exposes_the_api_key_or_dsn_password():
    settings = _settings(
        llm_api_key="gsk_super_secret_value",
        database_url="postgresql+asyncpg://civicpulse:hunter2@database:5432/civicpulse",
    )

    dumped = settings.safe_dump()

    assert dumped["llm_api_key"] == "***set***"
    assert "hunter2" not in str(dumped)
    assert "civicpulse:hunter2" not in dumped["database_url"]


# --- Rule matching regressions ---------------------------------------------
# Each case below was a real misclassification seen on the live dashboard.


def test_rules_ignore_the_location_when_choosing_a_category():
    """'Main Ferozepur Road' filed a noise complaint under roads."""
    result = RuleBasedTriage().triage_sync(
        "Noise from the marriage hall generator goes on till 2am, elderly people cannot sleep.",
        "Main Ferozepur Road, Lahore",
    )
    assert result.category is Category.OTHER


def test_rules_match_whole_words_not_substrings():
    """'week' fired on 'weekend' and made a noise complaint high priority."""
    result = RuleBasedTriage().triage_sync(
        "Loud music from the hall every weekend, it is very disturbing.", "Lahore"
    )
    assert result.priority is not Priority.HIGH


def test_rules_still_match_plurals_and_stems():
    urgent = RuleBasedTriage().triage_sync(
        "Two children were injured when the drain overflowed for two weeks.", "Karachi"
    )
    assert urgent.priority is Priority.HIGH  # children, injured, overflowed, weeks
    assert urgent.category is Category.SANITATION


def test_rules_do_not_match_a_keyword_inside_another_word():
    """'meter' inside 'kilometer' must not make this an electricity complaint."""
    result = RuleBasedTriage().triage_sync(
        "The whole one kilometer stretch has potholes after the rain.", "Lahore"
    )
    assert result.category is Category.ROADS


@pytest.mark.parametrize(
    "text",
    [
        "Street light is remaining on the whole day also, electricity is wasting.",
        "Lamp post is broken and leaning towards the road, it can fall on parked cars.",
        "New poles were installed three months back but lights were never connected.",
    ],
)
def test_rules_file_streetlight_complaints_as_streetlights(text):
    """Each of these was filed under electricity, roads or other on the live
    dashboard: ties went to whichever category came first in the list."""
    assert RuleBasedTriage().triage_sync(text, "Rawalpindi").category is Category.STREETLIGHTS
