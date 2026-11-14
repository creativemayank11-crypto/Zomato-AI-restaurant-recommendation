"""Tests for enrichment fields, feature filters, strict mode, nearby fallback,
response cache, shared-store rate limiting, top-rated / feedback endpoints,
request IDs and the LLM retry policy. No live LLM calls."""
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import app
from config.settings import settings
from src.api import routes
from src.api.rate_limit import recommend_limiter
from src.api.store import MemoryStore, StoreError, set_store
from src.data.preprocessor import (
    clean_phone,
    clean_url,
    extract_review_snippets,
    load_processed_data,
)
from src.engine.filter import filter_restaurants, relaxation_steps_from_message
from src.engine.recommender import is_transient_llm_error
from src.models.schema import RecommendationResponse, UserPreferences


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return load_processed_data()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# ETL helpers
# ---------------------------------------------------------------------------

def test_clean_phone_takes_first_number():
    assert clean_phone("+91 9108945277\r\n+91 8023456789") == "+91 9108945277"
    assert clean_phone("080 43755274") == "080 43755274"
    assert clean_phone(None) == ""
    assert clean_phone("n/a") == ""


def test_clean_url_strips_tracking_and_rejects_other_hosts():
    assert clean_url("https://www.zomato.com/bangalore/x-y?context=abc") == "https://www.zomato.com/bangalore/x-y"
    assert clean_url("javascript:alert(1)") == ""
    assert clean_url("https://evil.example/zomato") == ""


def test_review_snippets_prefer_high_ratings_and_skip_garbage():
    raw = str([
        ("Rated 2.0", "RATED\n  Meh place, food was cold and the service was very slow overall."),
        ("Rated 5.0", "RATED\n  Wonderful candlelit ambience, the pasta was fresh and the staff warm."),
        ("Rated 4.0", "RATED\n  Ã©Ã© mojibake text that should be skipped entirely, really skipped."),
        ("Rated 4.5", "RATED\n  short"),
    ])
    snippets = extract_review_snippets(raw)
    assert snippets[0].startswith("Wonderful candlelit ambience")
    assert all("Ã" not in s for s in snippets)
    assert all(len(s) >= 40 for s in snippets)
    assert extract_review_snippets("not a list") == []
    assert extract_review_snippets(None) == []


def test_processed_dataset_has_enrichment_columns(df):
    for col in ("address", "phone", "zomato_url", "rest_type", "online_order",
                "book_table", "dining_types", "zones", "review_snippets"):
        assert col in df.columns, col
    assert (df["zomato_url"].str.startswith("https://www.zomato.com/")).mean() > 0.95


# ---------------------------------------------------------------------------
# Filter: feature requirements, strict mode, nearby areas
# ---------------------------------------------------------------------------

def test_book_table_filter_only_returns_bookable(df):
    cands, _, _, _ = filter_restaurants(df, UserPreferences(location="Koramangala", book_table=True))
    assert cands and all(c.book_table for c in cands)


def test_dining_type_filter(df):
    cands, _, _, _ = filter_restaurants(df, UserPreferences(location="Indiranagar", dining_type="Pubs and bars"))
    assert cands and all("Pubs and bars" in c.dining_types for c in cands)


def test_strict_mode_never_relaxes(df):
    prefs = UserPreferences(location="Kengeri", budget_tier="high", min_rating=4.8, strict=True)
    cands, relaxed, msg, _ = filter_restaurants(df, prefs)
    assert cands == [] and relaxed is False and msg is None


def test_nearby_areas_step_before_citywide(df):
    prefs = UserPreferences(location="Banashankari", cuisines=["Continental"], budget_tier="low", min_rating=4.8)
    _, relaxed, msg, _ = filter_restaurants(df, prefs)
    steps = relaxation_steps_from_message(msg)
    assert relaxed
    assert any(s.startswith("Included nearby Zomato areas") for s in steps), steps


def test_relaxation_steps_parsing():
    msg = "Search criteria relaxed: Budget widened to all price ranges; Minimum rating lowered from 4.5 to 4.0."
    assert relaxation_steps_from_message(msg) == [
        "Budget widened to all price ranges",
        "Minimum rating lowered from 4.5 to 4.0",
    ]
    assert relaxation_steps_from_message(None) == []


def test_candidates_carry_links_and_reviews(df):
    cands, _, _, _ = filter_restaurants(df, UserPreferences(location="Indiranagar"))
    assert any(c.zomato_url for c in cands)
    assert any(c.address for c in cands)


# ---------------------------------------------------------------------------
# LLM retry policy
# ---------------------------------------------------------------------------

def test_only_malformed_output_is_retried():
    class AuthenticationError(Exception):
        status_code = 401

    class RateLimitError(Exception):
        status_code = 429

    assert is_transient_llm_error(json.JSONDecodeError("bad", "{", 0))
    assert not is_transient_llm_error(AuthenticationError())
    assert not is_transient_llm_error(RateLimitError())   # the SDK already retried it
    assert not is_transient_llm_error(ValueError("Unsupported LLM provider"))


# ---------------------------------------------------------------------------
# API: options, cache, request IDs, top-rated, feedback
# ---------------------------------------------------------------------------

def test_options_include_new_fields_and_cache_header(client):
    resp = client.get("/api/v1/meta/options")
    data = resp.json()
    assert "public" in resp.headers["Cache-Control"]
    assert "Pubs and bars" in data["dining_types"]
    assert "Delivery" not in data["dining_types"]
    assert len(data["all_cuisines"]) > len(data["cuisines"])
    assert data["rating_options"] == [0.0, 3.5, 4.0, 4.5]


def test_request_id_header_generated_and_propagated(client):
    assert len(client.get("/health").headers["X-Request-ID"]) >= 6
    assert client.get("/health", headers={"X-Request-ID": "abc-123-xyz"}).headers["X-Request-ID"] == "abc-123-xyz"
    # Unsafe incoming values are replaced
    assert client.get("/health", headers={"X-Request-ID": "<script>"}).headers["X-Request-ID"] != "<script>"


def test_recommend_served_from_cache(client):
    payload = {"location": "Indiranagar", "max_recommendations": 3, "cuisines": ["Italian"]}
    key = routes.recommend_cache_key(UserPreferences(**payload))
    stored = RecommendationResponse(query_summary="cached answer", ai_generated=True)
    routes.get_store().set(key, stored.model_dump_json(), 60)

    resp = client.post("/api/v1/recommend", json=payload)
    assert resp.status_code == 200
    assert resp.headers["X-Cache"] == "HIT"
    assert resp.json()["query_summary"] == "cached answer"


def test_cache_key_ignores_cuisine_order_and_note_case():
    a = UserPreferences(location="BTM", cuisines=["Chinese", "Pizza"], additional_notes="Quiet  Spot")
    b = UserPreferences(location="btm", cuisines=["pizza", "chinese"], additional_notes="quiet spot")
    assert routes.recommend_cache_key(a) == routes.recommend_cache_key(b)


def test_deterministic_fallback_is_not_cached(monkeypatch):
    calls = []

    class SpyStore(MemoryStore):
        def set(self, key, value, ttl):
            calls.append(key)

    set_store(SpyStore())
    routes._cache_set("k", RecommendationResponse(ai_generated=False))
    assert calls == []
    routes._cache_set("k", RecommendationResponse(ai_generated=True))
    assert calls == ["k"]


def test_top_rated_endpoint(client):
    resp = client.get("/api/v1/top", params={"location": "Indiranagar", "limit": 3})
    assert resp.status_code == 200
    restaurants = resp.json()["restaurants"]
    assert 1 <= len(restaurants) <= 3
    ratings = [r["rating"] for r in restaurants]
    assert ratings == sorted(ratings, reverse=True)
    assert all(r["zomato_url"] for r in restaurants)


def test_feedback_endpoint(client):
    assert client.post("/api/v1/feedback", json={"restaurant_id": "ZOM_00001", "vote": "up"}).status_code == 204
    assert client.post("/api/v1/feedback", json={"restaurant_id": "ZOM_00001", "vote": "maybe"}).status_code == 422


# ---------------------------------------------------------------------------
# Shared-store rate limiting (fake Upstash-like store)
# ---------------------------------------------------------------------------

class FakeSharedStore(MemoryStore):
    """Behaves like UpstashStore but in memory; not a MemoryStore instance check target."""


class _Shared:
    """Wrapper so isinstance(store, MemoryStore) is False (selects the shared path)."""

    def __init__(self, fail=False):
        self._inner = FakeSharedStore()
        self.fail = fail

    def incr_window(self, key, window):
        if self.fail:
            raise StoreError("down")
        return self._inner.incr_window(key, window)

    def ttl(self, key):
        return self._inner.ttl(key)

    def get(self, key):
        return None

    def set(self, key, value, ttl):
        pass


def test_shared_store_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 1)
    set_store(_Shared())
    headers = {"X-Forwarded-For": "198.51.100.9"}
    # First call is allowed by the limiter (may then 200 or fall back); second is blocked
    from src.api.rate_limit import enforce_recommend_rate_limit  # noqa: F401
    store = routes.get_store()
    store.incr_window("rl:recommend:198.51.100.9", 60)  # use up the quota
    resp = client.post("/api/v1/recommend", json={"location": "BTM"}, headers=headers)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1


def test_shared_store_outage_falls_back_to_memory_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 1)
    set_store(_Shared(fail=True))
    recommend_limiter.check("198.51.100.10", limit=1)  # fill the in-memory window
    resp = client.post("/api/v1/recommend", json={"location": "BTM"}, headers={"X-Forwarded-For": "198.51.100.10"})
    assert resp.status_code == 429
