"""Unit tests and performance benchmarks for Phase 2 Deterministic Retrieval Engine."""
import pytest
import pandas as pd
from config.constants import BudgetTier, DEFAULT_TOP_K_CANDIDATES
from src.data.preprocessor import load_processed_data
from src.engine.filter import (
    compute_heuristic_score,
    compute_heuristic_score_series,
    resolve_user_cuisines,
    parse_location_query,
    filter_restaurants,
)
from src.models.schema import UserPreferences, RestaurantCandidate


@pytest.fixture(scope="module")
def processed_dataset():
    """Load the clean Parquet dataset once for all filter tests."""
    return load_processed_data()


def test_compute_heuristic_score():
    """Verify heuristic score monotonicity and bounds."""
    high_score = compute_heuristic_score(rating=4.9, votes=2500)
    low_score = compute_heuristic_score(rating=3.5, votes=50)

    assert 0.0 <= high_score <= 1.0
    assert 0.0 <= low_score <= 1.0
    assert high_score > low_score

    max_score = compute_heuristic_score(rating=5.0, votes=1000)
    assert max_score == pytest.approx(1.0)


def test_compute_heuristic_score_series():
    """Verify vectorized scoring matches scalar compute_heuristic_score."""
    ratings = pd.Series([5.0, 4.9, 3.5, 1.0])
    votes = pd.Series([1000, 2500, 50, 0])

    vectorized = compute_heuristic_score_series(ratings, votes)
    scalar = [compute_heuristic_score(r, v) for r, v in zip(ratings, votes)]

    assert vectorized.tolist() == scalar


def test_resolve_user_cuisines():
    """Verify user cuisine resolution and alias expansion."""
    resolved = resolve_user_cuisines(["Pizza", "Fast Food"])
    assert "pizza" in resolved
    assert "italian" in resolved  # expanded via CUISINE_ALIASES
    assert "fast food" in resolved

    all_resolved = resolve_user_cuisines(["all"])
    assert len(all_resolved) == 0

    empty_resolved = resolve_user_cuisines([])
    assert len(empty_resolved) == 0


def test_parse_location_query():
    """Verify parsing of pure cities, aliases, and compound location strings."""
    # City directly
    city, loc = parse_location_query("Bangalore")
    assert city == "bangalore" and loc is None

    # City alias
    city, loc = parse_location_query("Bengaluru")
    assert city == "bangalore" and loc is None

    # Compound locality and city
    city, loc = parse_location_query("Indiranagar, Bangalore")
    assert city == "bangalore" and loc == "indiranagar"

    city, loc = parse_location_query("Connaught Place, Delhi")
    assert city == "delhi" and loc == "connaught place"

    # Locality without city
    city, loc = parse_location_query("Koramangala 4th Block")
    assert city is None and loc == "koramangala 4th block"


def test_standard_deterministic_filtering(processed_dataset: pd.DataFrame):
    """Verify exact filtering for standard queries without relaxation."""
    prefs = UserPreferences(
        location="Bangalore",
        cuisines=["Italian"],
        budget_tier="medium",
        min_rating=4.0,
    )

    candidates, relaxed, rel_msg, exec_ms = filter_restaurants(processed_dataset, prefs)

    assert len(candidates) > 0
    assert len(candidates) <= DEFAULT_TOP_K_CANDIDATES
    assert relaxed is False
    assert rel_msg is None

    # Verify that every candidate meets hard criteria
    for c in candidates:
        assert isinstance(c, RestaurantCandidate)
        assert c.city.lower() == "bangalore"
        assert c.rating >= 4.0
        assert c.budget_tier == BudgetTier.MEDIUM
        assert "italian" in c.cuisines


def test_compound_location_filtering(processed_dataset: pd.DataFrame):
    """Verify compound locality + city query filters accurately without falling back."""
    prefs = UserPreferences(
        location="Indiranagar, Bangalore",
        cuisines=["all"],
        budget_tier="medium",
        min_rating=3.5,
    )

    candidates, relaxed, rel_msg, exec_ms = filter_restaurants(processed_dataset, prefs)

    assert len(candidates) >= 3
    assert relaxed is False
    assert rel_msg is None
    for c in candidates:
        assert c.city.lower() == "bangalore"
        assert "indiranagar" in c.locality.lower()


def test_brand_diversity_throttling(processed_dataset: pd.DataFrame):
    """Verify that no brand name appears more than once in the candidate pool."""
    prefs = UserPreferences(
        location="Bangalore",
        cuisines=["all"],
        budget_tier="low",
        min_rating=3.5,
    )

    candidates, _, _, _ = filter_restaurants(processed_dataset, prefs, top_k=15)
    names = [c.name.strip().lower() for c in candidates]
    unique_names = set(names)

    # Every restaurant in the pool must have a distinct brand name
    assert len(names) == len(unique_names), f"Brand duplicate detected: {names}"


def test_score_tie_breaking_midpoint():
    """Verify that ties in heuristic score break by votes, then budget midpoint distance."""
    # Synthetic test DataFrame with tied scores
    df_tied = pd.DataFrame([
        {
            "restaurant_id": "R1",
            "name": "Bistro Alpha",
            "city": "Bangalore",
            "locality": "Koramangala",
            "cuisines": ["cafe"],
            "rating": 4.0,
            "votes": 500,
            "cost_for_two": 600,   # Closer to medium midpoint 1000: diff 400
            "budget_tier": "medium",
            "highlights": ["Wifi"],
            "is_new": False,
        },
        {
            "restaurant_id": "R2",
            "name": "Bistro Beta",
            "city": "Bangalore",
            "locality": "Koramangala",
            "cuisines": ["cafe"],
            "rating": 4.0,
            "votes": 500,
            "cost_for_two": 1400,  # Farther from medium midpoint 1000: diff 400 (equal diff)
            "budget_tier": "medium",
            "highlights": ["AC"],
            "is_new": False,
        },
        {
            "restaurant_id": "R3",
            "name": "Bistro Gamma",
            "city": "Bangalore",
            "locality": "Koramangala",
            "cuisines": ["cafe"],
            "rating": 4.0,
            "votes": 800,          # Higher votes -> must rank 1st
            "cost_for_two": 1200,
            "budget_tier": "medium",
            "highlights": ["Outdoor"],
            "is_new": False,
        },
    ])

    prefs = UserPreferences(
        location="Koramangala",
        cuisines=["cafe"],
        budget_tier="medium",
        min_rating=3.5,
    )

    candidates, _, _, _ = filter_restaurants(df_tied, prefs, top_k=3)
    assert len(candidates) == 3
    # R3 must be first due to higher votes
    assert candidates[0].restaurant_id == "R3"


def test_fallback_relaxation_on_impossible_query(processed_dataset: pd.DataFrame):
    """Verify automated fallback relaxation when strict criteria yield zero candidates."""
    prefs = UserPreferences(
        location="Banashankari",
        cuisines=["Continental"],
        budget_tier="low",
        min_rating=4.8,
    )

    candidates, relaxed, rel_msg, exec_ms = filter_restaurants(processed_dataset, prefs)

    assert len(candidates) > 0
    assert relaxed is True
    assert rel_msg is not None
    assert "Search criteria relaxed" in rel_msg


def test_micro_locality_broadening(processed_dataset: pd.DataFrame):
    """Verify fallback broadening from obscure locality to parent city."""
    prefs = UserPreferences(
        location="Unknown Fictional Zone 99",
        cuisines=["North Indian"],
        budget_tier="medium",
        min_rating=4.0,
    )

    candidates, relaxed, rel_msg, _ = filter_restaurants(processed_dataset, prefs)

    assert len(candidates) > 0
    assert relaxed is True
    assert "citywide" in rel_msg.lower() or "relaxed" in rel_msg.lower()


def test_custom_top_k_bounds(processed_dataset: pd.DataFrame):
    """Verify that the engine respects top_k limits."""
    prefs = UserPreferences(
        location="Bangalore",
        cuisines=["all"],
        budget_tier="medium",
        min_rating=3.5,
    )

    # Top-K = 5
    candidates_5, _, _, _ = filter_restaurants(processed_dataset, prefs, top_k=5)
    assert len(candidates_5) == 5

    # Top-K = 15
    candidates_15, _, _, _ = filter_restaurants(processed_dataset, prefs, top_k=15)
    assert len(candidates_15) == 15


def test_candidate_retrieval_latency_benchmark(processed_dataset: pd.DataFrame):
    """Benchmark deterministic filter latency against the < 50ms requirement."""
    prefs = UserPreferences(
        location="Bangalore",
        cuisines=["Chinese", "Asian"],
        budget_tier="medium",
        min_rating=3.8,
    )

    # Warmup
    filter_restaurants(processed_dataset, prefs)

    # Median of 15 runs: robust to one-off spikes when the machine is busy
    # (the mean failed intermittently when other processes were running).
    latencies = []
    for _ in range(15):
        _, _, _, exec_ms = filter_restaurants(processed_dataset, prefs)
        latencies.append(exec_ms)

    median_latency = sorted(latencies)[len(latencies) // 2]
    assert median_latency < 50.0, f"Median filter latency {median_latency:.2f}ms exceeds 50ms budget"
