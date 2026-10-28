"""Domain constants, budget boundaries, and heuristics for Zomato AI Recommender."""
from enum import Enum
from typing import Dict, List, Set

class BudgetTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

# Cost for two boundaries (in INR)
BUDGET_BOUNDARIES: Dict[BudgetTier, Dict[str, float]] = {
    BudgetTier.LOW: {"min": 0, "max": 500},
    BudgetTier.MEDIUM: {"min": 500, "max": 1500},
    BudgetTier.HIGH: {"min": 1500, "max": float("inf")},
}

# Heuristic scoring weights for candidate pre-ranking
DEFAULT_RATING_WEIGHT: float = 0.7
DEFAULT_VOTES_WEIGHT: float = 0.3
VOTE_NORMALIZATION_CAP: int = 1000

# Number of candidates sent to the cognitive LLM reasoning layer
DEFAULT_TOP_K_CANDIDATES: int = 12
MIN_CANDIDATES_BEFORE_RELAXATION: int = 3
DEFAULT_RECOMMENDATIONS_COUNT: int = 3
MAX_RECOMMENDATIONS_COUNT: int = 5

# City aliases for robust input matching
CITY_ALIASES: Dict[str, str] = {
    "bengaluru": "bangalore",
    "bombay": "mumbai",
    "gurugram": "gurgaon",
    "calcutta": "kolkata",
    "madras": "chennai",
    "delhi ncr": "delhi",
    "new delhi": "delhi",
}

# Common Indian cuisine taxonomies and synonyms
CUISINE_ALIASES: Dict[str, str] = {
    "italien": "italian",
    "pizza": "italian",
    "pasta": "italian",
    "muglai": "mughlai",
    "burger": "fast food",
    "burgers": "fast food",
    "shakes": "beverages",
    "coffee": "cafe",
}

# Maximum character length for user-submitted additional notes (prompt injection mitigation)
MAX_USER_NOTES_LENGTH: int = 300

# Maximum character length for AI-generated recommendation reasons (UI card safety)
MAX_RATIONALE_LENGTH: int = 280
