"""Tests for the per-client rate limiter on /api/v1/recommend."""
import pytest
from fastapi.testclient import TestClient

from app import app
from config.settings import settings
from src.api.rate_limit import SlidingWindowRateLimiter, recommend_limiter

PAYLOAD = {"location": "Indiranagar", "max_recommendations": 3}


# ---------------------------------------------------------------------------
# Limiter unit tests (explicit clock, no sleeping)
# ---------------------------------------------------------------------------

def test_allows_up_to_limit_then_blocks():
    limiter = SlidingWindowRateLimiter(window_seconds=60)
    for i in range(3):
        assert limiter.check("a", limit=3, now=100.0 + i) is None
    retry_after = limiter.check("a", limit=3, now=103.0)
    assert retry_after == 57  # oldest hit (t=100) expires at t=160


def test_window_slides():
    limiter = SlidingWindowRateLimiter(window_seconds=60)
    limiter.check("a", limit=1, now=0.0)
    assert limiter.check("a", limit=1, now=30.0) is not None
    assert limiter.check("a", limit=1, now=60.5) is None


def test_clients_are_independent():
    limiter = SlidingWindowRateLimiter(window_seconds=60)
    assert limiter.check("a", limit=1, now=0.0) is None
    assert limiter.check("b", limit=1, now=0.0) is None
    assert limiter.check("a", limit=1, now=1.0) is not None


def test_zero_limit_disables():
    limiter = SlidingWindowRateLimiter(window_seconds=60)
    for i in range(100):
        assert limiter.check("a", limit=0, now=float(i)) is None


def test_idle_clients_are_swept():
    limiter = SlidingWindowRateLimiter(window_seconds=60)
    limiter.check("old", limit=5, now=0.0)
    limiter.check("new", limit=5, now=200.0)  # triggers a sweep
    assert "old" not in limiter._hits
    assert "new" in limiter._hits


# ---------------------------------------------------------------------------
# Endpoint behaviour (the limit is pre-filled so no LLM call is made)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_recommend_returns_429_when_limit_exceeded(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 1)
    recommend_limiter.check("203.0.113.7", limit=1)  # use up the client's quota

    resp = client.post("/api/v1/recommend", json=PAYLOAD, headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})

    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1
    body = resp.json()
    assert body["detail"]["error"] == "rate_limited"
    assert "Too many requests" in body["detail"]["message"]


def test_rate_limit_does_not_apply_to_other_endpoints(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 1)
    recommend_limiter.check("testclient", limit=1)
    for _ in range(3):
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/meta/options").status_code == 200
