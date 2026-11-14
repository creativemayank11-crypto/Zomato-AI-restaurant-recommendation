"""Pydantic data models and API schemas for Zomato AI Recommender."""
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from config.constants import (
    BudgetTier,
    MAX_USER_NOTES_LENGTH,
    MAX_RATIONALE_LENGTH,
    DEFAULT_RECOMMENDATIONS_COUNT,
    MAX_RECOMMENDATIONS_COUNT,
    CITY_ALIASES,
)

class UserPreferences(BaseModel):
    """User input criteria and subjective constraints."""
    location: str = Field(
        ...,
        min_length=2,
        description="Target city or locality (e.g., 'Bangalore', 'Connaught Place, Delhi')",
        examples=["Bangalore", "Delhi"]
    )
    cuisines: Optional[List[str]] = Field(
        default_factory=lambda: ["all"],
        description="List of preferred cuisines (e.g., ['Italian', 'Continental']) - optional",
        examples=[["Italian", "Chinese"]]
    )
    budget_tier: BudgetTier = Field(
        default=BudgetTier.MEDIUM,
        description="Budget bracket: 'low' (< ₹500), 'medium' (₹500-₹1500), 'high' (> ₹1500)",
        examples=["medium"]
    )
    min_rating: float = Field(
        default=3.5,
        ge=1.0,
        le=5.0,
        description="Minimum aggregate star rating threshold (1.0 to 5.0)",
        examples=[4.0]
    )
    additional_notes: Optional[str] = Field(
        default=None,
        max_length=MAX_USER_NOTES_LENGTH,
        description="Free-form subjective preferences (e.g. 'romantic anniversary spot', 'quiet cafe with wifi')",
        examples=["romantic quiet dinner with outdoor seating"]
    )
    max_recommendations: int = Field(
        default=DEFAULT_RECOMMENDATIONS_COUNT,
        ge=1,
        le=MAX_RECOMMENDATIONS_COUNT,
        description="Number of recommendations to return (1 to 5)"
    )

    @field_validator("location")
    @classmethod
    def normalize_location(cls, v: str) -> str:
        clean = v.strip().lower()
        return CITY_ALIASES.get(clean, clean)

    @field_validator("cuisines", mode="before")
    @classmethod
    def clean_cuisines(cls, v) -> List[str]:
        if not v:
            return ["all"]
        if isinstance(v, list):
            cleaned = [c.strip().lower() for c in v if isinstance(c, str) and c.strip()]
            return cleaned if cleaned else ["all"]
        if isinstance(v, str):
            return [v.strip().lower()] if v.strip() else ["all"]
        return ["all"]


class RestaurantCandidate(BaseModel):
    """Normalized restaurant record pruned from tabular dataset."""
    restaurant_id: str = Field(..., description="Unique identifier for the restaurant")
    name: str = Field(..., description="Name of the restaurant")
    locality: str = Field(..., description="Locality or sub-area")
    city: str = Field(..., description="Parent city")
    cuisines: List[str] = Field(default_factory=list, description="List of cuisines served")
    cost_for_two: int = Field(..., ge=0, description="Estimated average cost for two in INR")
    budget_tier: BudgetTier = Field(..., description="Classified budget tier")
    rating: float = Field(..., ge=0.0, le=5.0, description="Aggregate user rating")
    votes: int = Field(default=0, ge=0, description="Total review votes count")
    highlights: Optional[List[str]] = Field(default_factory=list, description="Features or highlights")
    is_new: Optional[bool] = Field(default=False, description="Flag indicating newly opened/unrated")


class RestaurantRecommendation(BaseModel):
    """An individual restaurant recommendation with AI-generated reasoning."""
    restaurant_id: str = Field(..., description="Canonical ID matching source candidate")
    restaurant_name: str = Field(..., description="Restaurant name")
    cuisine: Optional[str] = Field(default="", description="Primary cuisines")
    locality: Optional[str] = Field(default="", description="Locality of the restaurant (from the dataset)")
    rating: Optional[float] = Field(default=0.0, description="Canonical rating score")
    estimated_cost_for_two: Optional[str] = Field(default="", description="Formatted cost string (e.g. '₹1,200 (Medium)')")
    recommendation_reason: str = Field(
        ...,
        max_length=MAX_RATIONALE_LENGTH,
        description="Grounded explanation linking user context and restaurant attributes"
    )

    @field_validator("recommendation_reason", mode="before")
    @classmethod
    def truncate_reason(cls, v):
        # Truncate instead of rejecting: a slightly long LLM rationale must not
        # invalidate the whole LLM response and force a deterministic fallback.
        if isinstance(v, str) and len(v) > MAX_RATIONALE_LENGTH:
            return v[: MAX_RATIONALE_LENGTH - 1].rstrip() + "…"
        return v


class RecommendationResponse(BaseModel):
    """Structured response contract emitted by the recommendation engine."""
    query_summary: str = Field(default="Curated recommendations based on your preferences", description="Synthesized summary of the user's intent")
    total_candidates_analyzed: int = Field(default=0, description="Number of pre-filtered candidates passed to LLM")
    relaxation_applied: bool = Field(
        default=False,
        description="Indicates whether fallback constraint relaxation was required"
    )
    relaxation_message: Optional[str] = Field(
        default=None,
        description="Explanation of any constraint relaxations applied"
    )
    recommendations: List[RestaurantRecommendation] = Field(
        default_factory=list,
        description="Top personalized recommendations"
    )


class HealthResponse(BaseModel):
    """Service health and diagnostics response."""
    status: str = "healthy"
    dataset_loaded: bool = False
    total_restaurants: int = 0
    version: str = "0.1.0"
    llm_provider: str = "gemini"
