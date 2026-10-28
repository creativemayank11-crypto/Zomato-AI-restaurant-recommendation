"""Unit tests validating Phase 0 project scaffolding, configuration, and data models."""
import os
import pytest
from pathlib import Path

from config.constants import (
    BudgetTier,
    BUDGET_BOUNDARIES,
    DEFAULT_RATING_WEIGHT,
    DEFAULT_VOTES_WEIGHT,
    CITY_ALIASES,
)
from config.settings import settings
from src.models.schema import (
    UserPreferences,
    RestaurantCandidate,
    RestaurantRecommendation,
    RecommendationResponse,
    HealthResponse,
)


def test_directory_structure():
    """Verify all required project directories and essential configuration files exist."""
    base_dir = Path(__file__).resolve().parent.parent
    
    required_dirs = [
        base_dir / "config",
        base_dir / "data" / "raw",
        base_dir / "data" / "processed",
        base_dir / "src" / "data",
        base_dir / "src" / "models",
        base_dir / "src" / "engine",
        base_dir / "src" / "api",
        base_dir / "src" / "utils",
        base_dir / "tests",
    ]
    for d in required_dirs:
        assert d.exists(), f"Required directory {d} is missing"
        assert d.is_dir(), f"Path {d} is not a directory"

    required_files = [
        base_dir / "requirements.txt",
        base_dir / ".env.example",
        base_dir / ".gitignore",
        base_dir / "config" / "constants.py",
        base_dir / "config" / "settings.py",
        base_dir / "src" / "models" / "schema.py",
    ]
    for f in required_files:
        assert f.exists(), f"Required file {f} is missing"


def test_constants_and_budget_boundaries():
    """Verify domain constants and budget boundary definitions."""
    assert BudgetTier.LOW.value == "low"
    assert BudgetTier.MEDIUM.value == "medium"
    assert BudgetTier.HIGH.value == "high"
    
    assert BUDGET_BOUNDARIES[BudgetTier.LOW]["max"] == 500
    assert BUDGET_BOUNDARIES[BudgetTier.MEDIUM]["min"] == 500
    assert BUDGET_BOUNDARIES[BudgetTier.MEDIUM]["max"] == 1500
    assert BUDGET_BOUNDARIES[BudgetTier.HIGH]["min"] == 1500
    
    assert DEFAULT_RATING_WEIGHT + DEFAULT_VOTES_WEIGHT == pytest.approx(1.0)
    assert CITY_ALIASES["bengaluru"] == "bangalore"


def test_settings_initialization():
    """Verify settings loads default environment values."""
    assert settings.DEFAULT_LLM_PROVIDER in ("gemini", "openai", "groq")
    assert settings.TEMPERATURE == pytest.approx(0.2)
    assert settings.API_PORT == 8000
    assert isinstance(settings.DEBUG, bool)


def test_user_preferences_model_validation():
    """Verify UserPreferences schema validation and normalization."""
    # Valid model with alias normalization (Bengaluru -> bangalore)
    prefs = UserPreferences(
        location="  Bengaluru  ",
        cuisines=["Italian", "Chinese"],
        budget_tier="medium",
        min_rating=4.0,
        additional_notes="Quiet anniversary dinner"
    )
    assert prefs.location == "bangalore"
    assert prefs.cuisines == ["italian", "chinese"]
    assert prefs.budget_tier == BudgetTier.MEDIUM
    assert prefs.min_rating == 4.0
    assert prefs.max_recommendations == 3


def test_user_preferences_invalid_rating():
    """Verify min_rating constraint bounds (1.0 to 5.0)."""
    with pytest.raises(Exception):
        UserPreferences(
            location="Delhi",
            min_rating=6.0  # Invalid > 5.0
        )

    with pytest.raises(Exception):
        UserPreferences(
            location="Delhi",
            min_rating=0.5  # Invalid < 1.0
        )


def test_user_preferences_invalid_budget():
    """Verify invalid budget tier rejection."""
    with pytest.raises(Exception):
        UserPreferences(
            location="Delhi",
            budget_tier="ultra_luxury"  # Invalid tier
        )


def test_restaurant_candidate_model():
    """Verify RestaurantCandidate model initialization."""
    candidate = RestaurantCandidate(
        restaurant_id="ZOM_101",
        name="Toscano",
        locality="Indiranagar",
        city="Bangalore",
        cuisines=["italian", "continental"],
        cost_for_two=1500,
        budget_tier=BudgetTier.MEDIUM,
        rating=4.5,
        votes=1240,
        highlights=["Outdoor Seating", "Wine"]
    )
    assert candidate.restaurant_id == "ZOM_101"
    assert candidate.rating == 4.5
    assert candidate.cost_for_two == 1500


def test_recommendation_response_model():
    """Verify structured RecommendationResponse schema."""
    rec = RestaurantRecommendation(
        restaurant_id="ZOM_101",
        restaurant_name="Toscano",
        cuisine="Italian, Continental",
        rating=4.5,
        estimated_cost_for_two="₹1,500 (Medium)",
        recommendation_reason="Perfect match for your Italian preference with artisanal pasta and relaxed outdoor seating."
    )
    response = RecommendationResponse(
        query_summary="Italian dinner in Bangalore",
        total_candidates_analyzed=12,
        relaxation_applied=False,
        recommendations=[rec]
    )
    assert len(response.recommendations) == 1
    assert response.recommendations[0].restaurant_name == "Toscano"
    assert response.total_candidates_analyzed == 12


def test_health_response_model():
    """Verify HealthResponse diagnostics schema."""
    health = HealthResponse(
        status="healthy",
        dataset_loaded=True,
        total_restaurants=8500,
        version="0.1.0"
    )
    assert health.status == "healthy"
    assert health.dataset_loaded is True
    assert health.total_restaurants == 8500
