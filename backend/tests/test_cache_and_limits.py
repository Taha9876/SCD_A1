"""Stats caching, cache invalidation, rate limiting, health and readiness."""
from __future__ import annotations

from app.config import Settings
from app.providers.cache import InMemoryCache
from app.providers.rate_limiter import RateLimiter

# --- /api/stats read-through cache -----------------------------------------


async def test_stats_first_call_is_a_miss_then_a_hit(client, valid_complaint):
    await client.post("/api/complaints", json=valid_complaint)

    first = await client.get("/api/stats")
    second = await client.get("/api/stats")

    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert second.json()["total"] == first.json()["total"]


async def test_stats_aggregate_by_category_and_priority(client):
    await client.post(
        "/api/complaints",
        json={
            "text": "Burst water main flooding Street 12 since fajr this morning.",
            "location": "Street 12, Islamabad",
        },
    )
    await client.post(
        "/api/complaints",
        json={
            "text": "Garbage has not been lifted from our lane since two weeks now.",
            "location": "Lane 6, Karachi",
        },
    )

    body = (await client.get("/api/stats")).json()

    assert body["total"] == 2
    assert body["by_category"]["water"] == 1
    assert body["by_category"]["sanitation"] == 1
    assert body["by_status"]["open"] == 2


async def test_write_invalidates_the_stats_cache(client, valid_complaint):
    """A citizen who submits and immediately opens the dashboard must see
    their own report, not a number up to 30 seconds stale."""
    await client.get("/api/stats")  # populate
    assert (await client.get("/api/stats")).headers["X-Cache"] == "HIT"

    await client.post("/api/complaints", json=valid_complaint)

    after = await client.get("/api/stats")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["total"] == 1


async def test_status_change_also_invalidates_stats(client, valid_complaint):
    created = (await client.post("/api/complaints", json=valid_complaint)).json()
    await client.get("/api/stats")
    assert (await client.get("/api/stats")).headers["X-Cache"] == "HIT"

    await client.patch(f"/api/complaints/{created['id']}/status", json={"status": "in_progress"})

    after = await client.get("/api/stats")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["by_status"]["in_progress"] == 1


# --- Rate limiter ----------------------------------------------------------


async def test_rate_limiter_allows_up_to_the_limit_then_blocks():
    limiter = RateLimiter(InMemoryCache(), limit=3, window_seconds=60)

    decisions = [await limiter.check("10.0.0.1") for _ in range(4)]

    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert decisions[-1].retry_after_seconds >= 1
    assert decisions[0].remaining == 2


async def test_rate_limiter_is_keyed_per_client():
    limiter = RateLimiter(InMemoryCache(), limit=1, window_seconds=60)

    assert (await limiter.check("10.0.0.1")).allowed is True
    assert (await limiter.check("10.0.0.2")).allowed is True
    assert (await limiter.check("10.0.0.1")).allowed is False


async def test_rate_limit_returns_429_with_retry_after(app, valid_complaint):
    """The limiter state lives in the shared cache, not in this process --
    which is why four HPA replicas still enforce one limit between them."""
    from httpx import ASGITransport, AsyncClient

    from app.config import get_settings

    limited = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://unused",
        triage_provider="simulated",
        rate_limit_requests=2,
        rate_limit_window_seconds=60,
    )
    app.dependency_overrides[get_settings] = lambda: limited

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        first = await c.post("/api/complaints", json=valid_complaint)
        second = await c.post(
            "/api/complaints",
            json={**valid_complaint, "text": valid_complaint["text"] + " Second report."},
        )
        third = await c.post(
            "/api/complaints",
            json={**valid_complaint, "text": valid_complaint["text"] + " Third report."},
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert third.status_code == 429
    assert third.json()["error"] == "rate_limited"
    assert int(third.headers["Retry-After"]) >= 1


# --- Probes ----------------------------------------------------------------


async def test_health_does_not_touch_the_database(client, monkeypatch):
    """Liveness must not depend on Postgres: if it did, a database blip would
    restart every backend pod at once and make recovery slower."""
    import app.repositories.complaint_repo as repo_module

    async def explode(self):
        raise AssertionError("/health must not query the database")

    monkeypatch.setattr(repo_module.ComplaintRepository, "ping", explode)

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_ready_reports_200_when_dependencies_are_reachable(client):
    response = await client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["dependencies"]["database"] == "ok"
    assert body["dependencies"]["cache"] == "ok"


async def test_ready_returns_503_naming_the_failed_dependency(client, monkeypatch):
    import app.repositories.complaint_repo as repo_module

    async def explode(self):
        raise ConnectionRefusedError("postgres is down")

    monkeypatch.setattr(repo_module.ComplaintRepository, "ping", explode)

    response = await client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert "database" in body["status"]
    assert body["dependencies"]["cache"] == "ok"


async def test_metrics_endpoint_exposes_prometheus_text(client, valid_complaint):
    await client.post("/api/complaints", json=valid_complaint)

    response = await client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "civicpulse_requests_total" in body
    assert "civicpulse_request_duration_seconds_bucket" in body
    assert "civicpulse_triage_fallback_total" in body


async def test_metrics_label_uses_the_route_template_not_the_raw_path(client, valid_complaint):
    """Otherwise every UUID becomes its own label value and the time series
    cardinality grows without bound."""
    created = (await client.post("/api/complaints", json=valid_complaint)).json()
    await client.get(f"/api/complaints/{created['id']}")

    body = (await client.get("/metrics")).text

    assert "/api/complaints/{complaint_id}" in body
    assert created["id"] not in body
