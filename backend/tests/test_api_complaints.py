"""Integration tests over the real ASGI app: routes, validation, state machine."""
from __future__ import annotations

import pytest


async def test_submit_returns_201_with_triage_fields(client, valid_complaint):
    response = await client.post("/api/complaints", json=valid_complaint)

    assert response.status_code == 200  # deliberately wrong: proves the CI gate blocks a merge
    body = response.json()
    assert body["category"] == "water"
    assert body["priority"] == "high"  # "flooding" + "entering ground floors"
    assert body["status"] == "open"
    assert body["triaged_by"] == "simulated"
    assert body["ai_summary"]
    assert len(body["ai_summary"]) <= 140
    assert body["triage_latency_ms"] >= 0
    # The server tells the client what it may do next, so the client never
    # needs its own copy of the state machine.
    assert body["allowed_transitions"] == ["in_progress", "rejected"]


@pytest.mark.parametrize(
    ("payload", "bad_field"),
    [
        ({"text": "short", "location": "Street 12, Islamabad"}, "text"),
        ({"text": "x" * 2001, "location": "Street 12, Islamabad"}, "text"),
        ({"text": "A valid complaint about water supply.", "location": "ab"}, "location"),
        ({"location": "Street 12, Islamabad"}, "text"),
    ],
)
async def test_validation_errors_are_field_level(client, payload, bad_field):
    response = await client.post("/api/complaints", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "validation_error"
    # A citizen needs to know which box to fix, not that "an error occurred".
    assert any(f["field"] == bad_field for f in body["fields"])


async def test_get_by_id_round_trips(client, valid_complaint):
    created = (await client.post("/api/complaints", json=valid_complaint)).json()

    response = await client.get(f"/api/complaints/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_unknown_id_is_404(client):
    response = await client.get("/api/complaints/00000000-0000-4000-8000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


async def test_list_filters_and_paginates(client):
    await client.post(
        "/api/complaints",
        json={
            "text": "Burst water main flooding the whole street since morning.",
            "location": "Street 12, Islamabad",
        },
    )
    await client.post(
        "/api/complaints",
        json={
            "text": "Street lights of our lane are not working since last month.",
            "location": "Lane 9, Rawalpindi",
        },
    )

    all_items = await client.get("/api/complaints")
    assert all_items.json()["total"] == 2

    filtered = await client.get("/api/complaints", params={"category": "streetlights"})
    body = filtered.json()
    assert body["total"] == 1
    assert body["items"][0]["category"] == "streetlights"

    paged = await client.get("/api/complaints", params={"page": 1, "page_size": 1})
    assert len(paged.json()["items"]) == 1
    assert paged.json()["pages"] == 2


async def test_page_size_is_capped_at_100(client):
    response = await client.get("/api/complaints", params={"page_size": 500})
    assert response.status_code == 400


async def test_valid_status_transition_succeeds(client, valid_complaint):
    created = (await client.post("/api/complaints", json=valid_complaint)).json()

    response = await client.patch(
        f"/api/complaints/{created['id']}/status", json={"status": "in_progress"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    assert response.json()["allowed_transitions"] == ["rejected", "resolved"]


async def test_invalid_transition_is_409_naming_the_transition(client, valid_complaint):
    created = (await client.post("/api/complaints", json=valid_complaint)).json()

    response = await client.patch(
        f"/api/complaints/{created['id']}/status", json={"status": "resolved"}
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "invalid_transition"
    assert body["current_status"] == "open"
    assert body["attempted_status"] == "resolved"
    # The operator can act on this message; "error" is not actionable.
    assert "open -> resolved" in body["detail"]
    assert body["allowed_transitions"] == ["in_progress", "rejected"]


async def test_terminal_status_rejects_every_transition(client, valid_complaint):
    created = (await client.post("/api/complaints", json=valid_complaint)).json()
    await client.patch(f"/api/complaints/{created['id']}/status", json={"status": "rejected"})

    response = await client.patch(
        f"/api/complaints/{created['id']}/status", json={"status": "in_progress"}
    )

    assert response.status_code == 409
    assert "terminal" in response.json()["detail"]


async def test_request_id_is_propagated_when_supplied(client, valid_complaint):
    response = await client.post(
        "/api/complaints", json=valid_complaint, headers={"X-Request-ID": "trace-me-123"}
    )
    assert response.headers["X-Request-ID"] == "trace-me-123"


async def test_request_id_is_generated_when_absent(client):
    response = await client.get("/api/complaints")
    assert response.headers.get("X-Request-ID")
