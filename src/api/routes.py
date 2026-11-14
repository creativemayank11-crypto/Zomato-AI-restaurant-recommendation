"""FastAPI route definitions: /health, /api/v1/meta/options, /api/v1/recommend."""
import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from config.settings import settings
from src.api.dependencies import get_dataset, get_llm_client, get_llm_provider
from src.api.rate_limit import enforce_recommend_rate_limit
from src.engine.filter import filter_restaurants
from src.engine.recommender import generate_recommendations
from src.models.schema import (
    HealthResponse,
    RecommendationResponse,
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

@router.get(
    "/api/v1/meta/options",
    summary="Get filter options for UI dropdowns",
    tags=["Metadata"],
    response_model=Dict[str, Any],
)
def get_meta_options() -> Dict[str, Any]:
    """Return available localities, top cuisines, and budget tiers for frontend dropdowns."""
    df = get_dataset()

    # All unique localities present in dataset, sorted alphabetically
    all_localities: List[str] = sorted(
        [str(loc) for loc in df["locality"].dropna().unique().tolist() if str(loc).strip()]
    )

    # Flatten cuisine lists and count occurrences
    from collections import Counter
    cuisine_counts: Counter = Counter(c for row in df["cuisines"] for c in row)
    top_cuisines: List[str] = [
        c.title() for c, _ in cuisine_counts.most_common(30)
    ]

    budget_tiers = [
        {"value": "low", "label": "Low (< ₹500)"},
        {"value": "medium", "label": "Medium (₹500 – ₹1,500)"},
        {"value": "high", "label": "High (> ₹1,500)"},
    ]

    return {
        "localities": all_localities,
        "cuisines": top_cuisines,
        "budget_tiers": budget_tiers,
        "rating_range": {"min": 1.0, "max": 5.0, "step": 0.5},
        "total_restaurants": len(df),
    }


# ---------------------------------------------------------------------------
# Core Recommendation Endpoint
# ---------------------------------------------------------------------------

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
) -> RecommendationResponse:
    """Execute the full pipeline: deterministic filter → Groq LLM → anti-hallucination guard.
    
    Gracefully degrades to deterministic top-K recommendations if the LLM API key
    is absent or the provider returns an error after retries.
    """
    t_start = time.perf_counter()
    df = get_dataset()
    llm_client = get_llm_client()
    provider = get_llm_provider()

    try:
        candidates, relaxed, rel_msg, filter_ms = filter_restaurants(df, preferences)

        response = generate_recommendations(
            preferences=preferences,
            candidates=candidates,
            relaxation_applied=relaxed,
            relaxation_message=rel_msg,
            provider=provider,
            llm_client=llm_client,
        )

        total_ms = round((time.perf_counter() - t_start) * 1000, 1)
        logger.info(
            "Recommend: location=%s provider=%s filter=%.1fms total=%.1fms candidates=%d recs=%d",
            preferences.location,
            provider,
            filter_ms,
            total_ms,
            len(candidates),
            len(response.recommendations),
        )

        return response

    except Exception as exc:
        logger.exception("Unexpected error in /api/v1/recommend: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "recommendation_pipeline_error",
                "message": str(exc),
            },
        )
