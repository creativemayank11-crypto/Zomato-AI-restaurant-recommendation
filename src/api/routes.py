"""FastAPI route definitions: health, options, recommend, top-rated and feedback."""
import hashlib
import json
import logging
import time
from collections import Counter
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from config.settings import settings
from src.api.dependencies import get_dataset, get_llm_client, get_llm_provider
from src.api.rate_limit import client_identifier, enforce_recommend_rate_limit
from src.api.store import StoreError, get_store
from src.engine.filter import dataframe_to_candidates, filter_restaurants
from src.engine.recommender import build_grounded_recommendation, generate_recommendations
from src.models.schema import (
    HealthResponse,
    RecommendationResponse,
    RestaurantRecommendation,
    UserPreferences,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    tags=["System"],
)
def health_check() -> HealthResponse:
    """Return service health, dataset status, and LLM provider details."""
    try:
        df = get_dataset()
        dataset_loaded = True
        total_restaurants = len(df)
    except RuntimeError:
        dataset_loaded = False
        total_restaurants = 0

    return HealthResponse(
        status="healthy" if dataset_loaded else "degraded",
        dataset_loaded=dataset_loaded,
        total_restaurants=total_restaurants,
        version=settings.APP_VERSION,
        llm_provider=get_llm_provider(),
    )


# ---------------------------------------------------------------------------
# Metadata / Options
# ---------------------------------------------------------------------------

_options_cache: Dict[int, Dict[str, Any]] = {}


def build_meta_options(df) -> Dict[str, Any]:
    """Compute dropdown options once per loaded dataset (it never changes at runtime)."""
    key = id(df)
    cached = _options_cache.get(key)
    if cached is not None:
        return cached

    localities: List[str] = sorted(
        str(loc) for loc in df["locality"].dropna().unique().tolist() if str(loc).strip()
    )
    cuisine_counts: Counter = Counter(c for row in df["cuisines"] for c in row)
    ranked_cuisines = [c.title() for c, _ in cuisine_counts.most_common()]
    dining_types: List[str] = []
    if "dining_types" in df.columns:
        type_counts: Counter = Counter(t for row in df["dining_types"] for t in row)
        dining_types = [t for t, _ in type_counts.most_common() if t not in ("Delivery", "Dine-out")]

    options = {
        "localities": localities,
        "cuisines": ranked_cuisines[:30],          # most popular, for the default chip list
        "all_cuisines": ranked_cuisines,           # everything, for the cuisine search box
        "dining_types": dining_types,              # e.g. Buffet, Cafes, Pubs and bars
        "budget_tiers": [
            {"value": "low", "label": "Low (< ₹500)"},
            {"value": "medium", "label": "Medium (₹500 – ₹1,500)"},
            {"value": "high", "label": "High (> ₹1,500)"},
        ],
        "rating_options": [0.0, 3.5, 4.0, 4.5],
        "rating_range": {"min": 1.0, "max": 5.0, "step": 0.5},
        "total_restaurants": len(df),
    }
    _options_cache.clear()
    _options_cache[key] = options
    return options


@router.get(
    "/api/v1/meta/options",
    summary="Get filter options for UI dropdowns",
    tags=["Metadata"],
    response_model=Dict[str, Any],
)
def get_meta_options(response: Response) -> Dict[str, Any]:
    """Return localities, cuisines, dining types and budget tiers for the UI."""
    response.headers["Cache-Control"] = "public, max-age=3600"
    return build_meta_options(get_dataset())


# ---------------------------------------------------------------------------
# Core Recommendation Endpoint
# ---------------------------------------------------------------------------

def recommend_cache_key(preferences: UserPreferences) -> str:
    """Stable key for a normalized request (order-insensitive cuisines, trimmed notes)."""
    data = preferences.model_dump(mode="json")
    data["cuisines"] = sorted(data.get("cuisines") or [])
    if data.get("additional_notes"):
        data["additional_notes"] = " ".join(data["additional_notes"].lower().split())
    data["provider"] = get_llm_provider()
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]
    return f"rec:v1:{digest}"


def _cache_get(key: str) -> Optional[RecommendationResponse]:
    if settings.RECOMMEND_CACHE_TTL_SECONDS <= 0:
        return None
    try:
        raw = get_store().get(key)
        return RecommendationResponse.model_validate_json(raw) if raw else None
    except (StoreError, ValueError) as exc:
        logger.warning("Recommendation cache read failed: %s", exc)
        return None


def _cache_set(key: str, value: RecommendationResponse) -> None:
    # Only cache genuine AI answers: a deterministic fallback (e.g. Groq was
    # rate-limited) should not be served again for the whole TTL.
    if settings.RECOMMEND_CACHE_TTL_SECONDS <= 0 or not value.ai_generated:
        return
    try:
        get_store().set(key, value.model_dump_json(), settings.RECOMMEND_CACHE_TTL_SECONDS)
    except StoreError as exc:
        logger.warning("Recommendation cache write failed: %s", exc)


@router.post(
    "/api/v1/recommend",
    response_model=RecommendationResponse,
    summary="Get AI-powered restaurant recommendations",
    tags=["Recommendations"],
    dependencies=[Depends(enforce_recommend_rate_limit)],
    responses={429: {"description": "Rate limit exceeded (see RATE_LIMIT_PER_MINUTE)"}},
)
def recommend(
    preferences: UserPreferences,
    request: Request,
    response: Response,
) -> RecommendationResponse:
    """Execute the full pipeline: deterministic filter → Groq LLM → anti-hallucination guard.

    Identical requests are served from cache for RECOMMEND_CACHE_TTL_SECONDS.
    Gracefully degrades to deterministic top-K recommendations if the LLM API key
    is absent or the provider returns an error after retries.
    """
    t_start = time.perf_counter()
    request_id = getattr(request.state, "request_id", "-")
    cache_key = recommend_cache_key(preferences)

    cached = _cache_get(cache_key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        _log_recommend(request_id, preferences, cached, cache="hit", filter_ms=0.0,
                       t_start=t_start, candidates=None)
        return cached

    df = get_dataset()
    llm_client = get_llm_client()
    provider = get_llm_provider()

    try:
        candidates, relaxed, rel_msg, filter_ms = filter_restaurants(df, preferences)

        result = generate_recommendations(
            preferences=preferences,
            candidates=candidates,
            relaxation_applied=relaxed,
            relaxation_message=rel_msg,
            provider=provider,
            llm_client=llm_client,
        )
    except Exception as exc:
        logger.exception("Unexpected error in /api/v1/recommend [%s]: %s", request_id, exc)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "recommendation_pipeline_error",
                "message": "The recommendation engine hit an unexpected error. Please try again.",
                "request_id": request_id,
            },
        )

    _cache_set(cache_key, result)
    response.headers["X-Cache"] = "MISS"
    _log_recommend(request_id, preferences, result, cache="miss", filter_ms=filter_ms,
                   t_start=t_start, candidates=len(candidates))
    return result


def _log_recommend(request_id, preferences, result, cache, filter_ms, t_start, candidates) -> None:
    """One structured (JSON) log line per request for dashboards / log search."""
    logger.info(
        "recommend %s",
        json.dumps({
            "request_id": request_id,
            "location": preferences.location,
            "budget": preferences.budget_tier.value,
            "min_rating": preferences.min_rating,
            "cuisines": preferences.cuisines,
            "has_notes": bool(preferences.additional_notes),
            "filters": {
                "book_table": preferences.book_table,
                "online_order": preferences.online_order,
                "dining_type": preferences.dining_type,
                "strict": preferences.strict,
            },
            "provider": get_llm_provider(),
            "cache": cache,
            "ai_generated": result.ai_generated,
            "relaxed": result.relaxation_applied,
            "candidates": candidates,
            "recs": len(result.recommendations),
            "filter_ms": round(filter_ms, 1),
            "total_ms": round((time.perf_counter() - t_start) * 1000, 1),
        }, ensure_ascii=False),
    )


# ---------------------------------------------------------------------------
# Top-rated (no LLM) — used for the empty state
# ---------------------------------------------------------------------------

class TopRatedResponse(BaseModel):
    location: str
    restaurants: List[RestaurantRecommendation]


@router.get(
    "/api/v1/top",
    response_model=TopRatedResponse,
    summary="Highest-rated restaurants in a locality (no LLM call)",
    tags=["Recommendations"],
)
def top_rated(
    response: Response,
    location: str = Query("Bangalore", min_length=2, max_length=80),
    limit: int = Query(4, ge=1, le=8),
) -> TopRatedResponse:
    """Deterministic top picks by rating and votes; cheap enough to show on page load."""
    prefs = UserPreferences(location=location, min_rating=1.0, max_recommendations=min(limit, 5))
    df = get_dataset()
    loc = prefs.location
    mask = df["locality"].str.lower().str.contains(loc, regex=False, na=False)
    if loc in ("bangalore", "bengaluru") or not mask.any():
        mask = df["locality"].notna()
    pool = df[mask & (df["votes"] >= 100)]
    if pool.empty:
        pool = df[mask]
    pool = pool.sort_values(["rating", "votes"], ascending=[False, False])
    pool = pool.drop_duplicates(subset=["name"]).head(limit)

    recs = [
        build_grounded_recommendation(
            c, f"Rated {c.rating:.1f} by {c.votes:,} diners — one of the best-rated spots in {c.locality}."
        )
        for c in dataframe_to_candidates(pool)
    ]
    response.headers["Cache-Control"] = "public, max-age=3600"
    return TopRatedResponse(location=location, restaurants=recs)


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    restaurant_id: str = Field(..., min_length=1, max_length=20)
    vote: Literal["up", "down"]
    query_summary: Optional[str] = Field(default=None, max_length=300)


@router.post(
    "/api/v1/feedback",
    status_code=204,
    summary="Record a thumbs up / down on a recommendation",
    tags=["Recommendations"],
)
def feedback(payload: FeedbackRequest, request: Request) -> Response:
    """Log feedback as a structured line (no database; read it from the logs)."""
    logger.info("feedback %s", json.dumps({
        "request_id": getattr(request.state, "request_id", "-"),
        "client": hashlib.sha256(client_identifier(request).encode()).hexdigest()[:12],
        "restaurant_id": payload.restaurant_id,
        "vote": payload.vote,
        "query_summary": payload.query_summary,
    }, ensure_ascii=False))
    return Response(status_code=204)
