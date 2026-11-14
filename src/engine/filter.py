"""Deterministic multi-criteria retrieval, candidate scoring, and fallback relaxation engine."""
import time
import re
import difflib
import logging
from typing import Dict, List, Optional, Set, Tuple
import numpy as np
import pandas as pd

from config.constants import (
    BudgetTier,
    BUDGET_BOUNDARIES,
    CITY_ALIASES,
    CUISINE_ALIASES,
    DEFAULT_RATING_WEIGHT,
    DEFAULT_VOTES_WEIGHT,
    VOTE_NORMALIZATION_CAP,
    DEFAULT_TOP_K_CANDIDATES,
    MIN_CANDIDATES_BEFORE_RELAXATION,
)
from src.models.schema import UserPreferences, RestaurantCandidate

logger = logging.getLogger(__name__)

# Midpoints of budget tiers for tie-breaking heuristics
BUDGET_MIDPOINTS: Dict[BudgetTier, float] = {
    BudgetTier.LOW: 250.0,
    BudgetTier.MEDIUM: 1000.0,
    BudgetTier.HIGH: 2500.0,
}

KNOWN_METRO_CITIES: Set[str] = {
    "bangalore", "delhi", "mumbai", "hyderabad", "chennai", "kolkata",
    "pune", "gurgaon", "noida", "ahmedabad", "jaipur", "chandigarh"
}


def compute_heuristic_score(
    rating: float,
    votes: int,
    rating_weight: float = DEFAULT_RATING_WEIGHT,
    votes_weight: float = DEFAULT_VOTES_WEIGHT,
) -> float:
    """Compute a composite heuristic score for ranking candidate restaurants.
    
    Formula: Score = (Rating / 5.0 * rating_weight) + (min(Votes / 1000, 1.0) * votes_weight)
    Normalizes both metrics to a [0.0, 1.0] scale.
    """
    norm_rating = min(max(rating / 5.0, 0.0), 1.0)
    norm_votes = min(max(votes / VOTE_NORMALIZATION_CAP, 0.0), 1.0)
    return round((norm_rating * rating_weight) + (norm_votes * votes_weight), 4)


def compute_heuristic_score_series(
    ratings: pd.Series,
    votes: pd.Series,
    rating_weight: float = DEFAULT_RATING_WEIGHT,
    votes_weight: float = DEFAULT_VOTES_WEIGHT,
) -> pd.Series:
    """Vectorized calculation of composite heuristic score for high-throughput candidate ranking."""
    norm_rating = (ratings.astype(float) / 5.0).clip(lower=0.0, upper=1.0)
    norm_votes = (votes.astype(float) / float(VOTE_NORMALIZATION_CAP)).clip(lower=0.0, upper=1.0)
    return ((norm_rating * rating_weight) + (norm_votes * votes_weight)).round(4)


def resolve_user_cuisines(
    user_cuisines: List[str],
    known_cuisines: Optional[Set[str]] = None,
) -> Set[str]:
    """Normalize and expand user cuisines using alias dictionary and fuzzy matching."""
    resolved: Set[str] = set()
    for c in user_cuisines:
        cleaned = c.strip().lower()
        if not cleaned or cleaned == "all":
            continue
        resolved.add(cleaned)
        # Check alias dictionary
        if cleaned in CUISINE_ALIASES:
            resolved.add(CUISINE_ALIASES[cleaned])
        # Fuzzy match against known cuisines if available
        elif known_cuisines and cleaned not in known_cuisines:
            matches = difflib.get_close_matches(cleaned, list(known_cuisines), n=1, cutoff=0.8)
            if matches:
                resolved.add(matches[0])
    return resolved


def parse_location_query(location_str: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse user location input into (city, locality).
    
    Handles:
    - Pure city: 'Bangalore', 'Delhi', 'Bengaluru'
    - Pure locality: 'Indiranagar', 'Koramangala 4th Block'
    - Compound locality + city: 'Indiranagar, Bangalore', 'Connaught Place, Delhi'
    """
    clean = location_str.strip().lower()
    if not clean:
        return None, None

    resolved = CITY_ALIASES.get(clean, clean)
    if resolved in KNOWN_METRO_CITIES:
        return resolved, None

    tokens = [t.strip() for t in re.split(r"[,;|\-/]", clean) if t.strip()]
    if len(tokens) >= 2:
        found_city = None
        locality_tokens = []
        for token in tokens:
            token_resolved = CITY_ALIASES.get(token, token)
            if token_resolved in KNOWN_METRO_CITIES and found_city is None:
                found_city = token_resolved
            else:
                locality_tokens.append(token)
        if found_city:
            loc = " ".join(locality_tokens) if locality_tokens else None
            return found_city, loc

    for city_name in KNOWN_METRO_CITIES:
        if clean.endswith(" " + city_name):
            loc = clean[:-len(city_name)-1].strip()
            return city_name, (loc if loc else None)

    return None, clean


def build_filter_mask(
    df: pd.DataFrame,
    city: Optional[str],
    locality: Optional[str],
    target_cuisines: Set[str],
    allowed_budget_tiers: Set[str],
    min_rating: float,
    strict_locality: bool = True,
) -> pd.Series:
    """Build a high-performance boolean Series mask for candidate filtering."""
    # 1. Location Condition
    if city and locality:
        city_mask = df["city"].str.lower() == city
        if strict_locality:
            loc_mask = df["locality"].str.lower().str.contains(locality, regex=False, na=False)
            location_mask = city_mask & loc_mask
        else:
            location_mask = city_mask
    elif city and not locality:
        location_mask = df["city"].str.lower() == city
    elif not city and locality:
        if strict_locality:
            loc_clean = locality.strip().lower()
            resolved_city = CITY_ALIASES.get(loc_clean, loc_clean)
            is_city = df["city"].str.lower() == resolved_city
            is_loc = df["locality"].str.lower().str.contains(loc_clean, regex=False, na=False)
            location_mask = is_city | is_loc
        else:
            location_mask = pd.Series(True, index=df.index)
    else:
        location_mask = pd.Series(True, index=df.index)

    # 2. Rating Condition
    rating_mask = df["rating"] >= min_rating

    # 3. Budget Condition
    budget_mask = df["budget_tier"].isin(allowed_budget_tiers)

    # Pre-filter using vectorized conditions
    pre_mask = location_mask & rating_mask & budget_mask

    # 4. Cuisine Condition (evaluated on surviving candidates for optimal performance)
    if not target_cuisines:
        return pre_mask

    final_mask = pd.Series(False, index=df.index)
    surviving_indices = df.index[pre_mask]

    if len(surviving_indices) == 0:
        return final_mask

    target_set = set(target_cuisines)
    surviving_cuisines = df.loc[surviving_indices, "cuisines"]

    matches = surviving_cuisines.apply(
        lambda c: bool(target_set.intersection(c)) if isinstance(c, (list, set, tuple, np.ndarray)) else False
    )

    final_mask.loc[surviving_indices] = matches
    return final_mask


def count_unique_brands(df_subset: pd.DataFrame) -> int:
    """Count number of distinct restaurant brand names in candidate pool."""
    if len(df_subset) == 0:
        return 0
    return df_subset["name"].str.lower().str.strip().nunique()


def build_feature_mask(
    df: pd.DataFrame, preferences: UserPreferences
) -> Tuple[Optional[pd.Series], List[str]]:
    """Mask for hard feature requirements; (None, []) when none are requested.

    Columns that are absent (e.g. synthetic test data) are ignored.
    """
    mask: Optional[pd.Series] = None
    labels: List[str] = []

    def _and(m: pd.Series) -> None:
        nonlocal mask
        mask = m if mask is None else (mask & m)

    if getattr(preferences, "book_table", False) and "book_table" in df.columns:
        _and(df["book_table"].fillna(False).astype(bool))
        labels.append("table booking")
    if getattr(preferences, "online_order", False) and "online_order" in df.columns:
        _and(df["online_order"].fillna(False).astype(bool))
        labels.append("online ordering")
    dining_type = getattr(preferences, "dining_type", None)
    if dining_type and "dining_types" in df.columns:
        wanted = dining_type.strip().lower()
        _and(df["dining_types"].apply(
            lambda ts: any(str(t).lower() == wanted for t in ts) if _is_listlike(ts) else False
        ))
        labels.append(f"'{dining_type}'")
    return mask, labels


def _is_listlike(v) -> bool:
    return isinstance(v, (list, tuple, set, np.ndarray))


def _str_field(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return str(v)


def _list_field(v) -> List[str]:
    return [str(x) for x in v] if _is_listlike(v) else []


def build_nearby_mask(df: pd.DataFrame, locality: str) -> Tuple[Optional[pd.Series], List[str]]:
    """Restaurants listed in the same Zomato zones as restaurants in `locality`.

    Zomato lists each restaurant under the nearby 'zones' (listed_in(city)) it
    delivers to or is browsable from, so shared zones are a good proxy for
    'nearby'. Returns (None, []) when the data has no zone information.
    """
    if "zones" not in df.columns:
        return None, []
    loc_mask = df["locality"].str.lower().str.contains(locality, regex=False, na=False)
    zones: List[str] = []
    for zs in df.loc[loc_mask, "zones"]:
        if _is_listlike(zs):
            for z in zs:
                if z not in zones:
                    zones.append(str(z))
    if not zones:
        return None, []
    zone_set = set(zones)
    mask = df["zones"].apply(lambda zs: _is_listlike(zs) and not zone_set.isdisjoint(zs))
    return mask, sorted(zones)


def relaxation_steps_from_message(message: Optional[str]) -> List[str]:
    """Split a relaxation message back into its individual, user-facing steps."""
    if not message:
        return []
    body = message
    prefix = "Search criteria relaxed:"
    if body.startswith(prefix):
        body = body[len(prefix):]
    body = body.strip().rstrip(".")
    return [s.strip() for s in body.split(";") if s.strip()]


def filter_restaurants(
    df: pd.DataFrame,
    preferences: UserPreferences,
    top_k: int = DEFAULT_TOP_K_CANDIDATES,
) -> Tuple[List[RestaurantCandidate], bool, Optional[str], float]:
    """Retrieve, rank, and prune candidate restaurants based on user preferences.
    
    Returns:
        Tuple containing:
        - List[RestaurantCandidate]: Top K candidate models
        - bool: relaxation_applied (True if fallback relaxation was triggered)
        - Optional[str]: relaxation_message (Description of applied relaxations)
        - float: execution_time_ms (Latency in milliseconds)
    """
    start_time = time.perf_counter()

    city, locality = parse_location_query(preferences.location)
    target_cuisines = resolve_user_cuisines(preferences.cuisines)
    requested_budget = preferences.budget_tier.value
    allowed_budgets = {requested_budget}
    min_rating = preferences.min_rating
    strict = bool(getattr(preferences, "strict", False))
    relaxation_reasons: List[str] = []

    # Hard feature requirements (table booking, online ordering, listing category).
    # They narrow the whole search space before the location/budget/rating cascade.
    feature_mask, feature_labels = build_feature_mask(df, preferences)
    if feature_mask is not None:
        if feature_mask.any() or strict:
            df = df[feature_mask]
        else:
            relaxation_reasons.append(
                f"No restaurants offer {' + '.join(feature_labels)}, so that requirement was dropped"
            )

    # Attempt 1: Strict Filtering
    mask = build_filter_mask(
        df,
        city=city,
        locality=locality,
        target_cuisines=target_cuisines,
        allowed_budget_tiers=allowed_budgets,
        min_rating=min_rating,
        strict_locality=True,
    )
    candidates_df = df[mask].copy()

    relaxation_applied = bool(relaxation_reasons)

    # Automated Fallback Relaxation Cascade if candidate unique brands < MIN_CANDIDATES_BEFORE_RELAXATION.
    # strict=True disables it: the caller prefers no results over broadened ones.
    if not strict and count_unique_brands(candidates_df) < MIN_CANDIDATES_BEFORE_RELAXATION:
        relaxation_applied = True
        logger.info(
            "Unique candidates (%d) below threshold (%d). Triggering fallback relaxation cascade...",
            count_unique_brands(candidates_df),
            MIN_CANDIDATES_BEFORE_RELAXATION,
        )

        # Step 1: Broaden Budget Tier
        if requested_budget == BudgetTier.LOW.value:
            allowed_budgets = {BudgetTier.LOW.value, BudgetTier.MEDIUM.value}
            relaxation_reasons.append("Budget widened to include medium (₹500–₹1,500)")
        elif requested_budget == BudgetTier.HIGH.value:
            allowed_budgets = {BudgetTier.MEDIUM.value, BudgetTier.HIGH.value}
            relaxation_reasons.append("Budget widened to include medium (₹500–₹1,500)")
        else:
            allowed_budgets = {BudgetTier.LOW.value, BudgetTier.MEDIUM.value, BudgetTier.HIGH.value}
            relaxation_reasons.append("Budget widened to all price ranges")

        mask = build_filter_mask(
            df,
            city=city,
            locality=locality,
            target_cuisines=target_cuisines,
            allowed_budget_tiers=allowed_budgets,
            min_rating=min_rating,
            strict_locality=True,
        )
        candidates_df = df[mask].copy()

        # Step 2: Relax Rating Floor (by 0.5 stars, floor at 3.0)
        if count_unique_brands(candidates_df) < MIN_CANDIDATES_BEFORE_RELAXATION and min_rating > 3.0:
            relaxed_rating = max(min_rating - 0.5, 3.0)
            relaxation_reasons.append(f"Minimum rating lowered from {min_rating:.1f} to {relaxed_rating:.1f}")
            min_rating = relaxed_rating

            mask = build_filter_mask(
                df,
                city=city,
                locality=locality,
                target_cuisines=target_cuisines,
                allowed_budget_tiers=allowed_budgets,
                min_rating=min_rating,
                strict_locality=True,
            )
            candidates_df = df[mask].copy()

        # Step 3: If locality has specific block/sector, broaden to base locality
        if count_unique_brands(candidates_df) < MIN_CANDIDATES_BEFORE_RELAXATION and locality:
            base_loc = re.sub(r"\s*\d+(st|nd|rd|th)?\s+(block|phase|stage|sector).*", "", locality).strip()
            if base_loc and base_loc != locality:
                relaxation_reasons.append(f"Searched all of {base_loc.title()} instead of {locality.title()}")
                locality = base_loc
                mask = build_filter_mask(
                    df,
                    city=city,
                    locality=locality,
                    target_cuisines=target_cuisines,
                    allowed_budget_tiers=allowed_budgets,
                    min_rating=min_rating,
                    strict_locality=True,
                )
                candidates_df = df[mask].copy()

        # Step 4a: Broaden to nearby areas (localities that share Zomato listing zones)
        if count_unique_brands(candidates_df) < MIN_CANDIDATES_BEFORE_RELAXATION and locality:
            nearby_mask, nearby_zones = build_nearby_mask(df, locality)
            if nearby_mask is not None:
                base = build_filter_mask(
                    df,
                    city=city,
                    locality=None,
                    target_cuisines=target_cuisines,
                    allowed_budget_tiers=allowed_budgets,
                    min_rating=min_rating,
                    strict_locality=False,
                )
                nearby_df = df[base & nearby_mask].copy()
                if count_unique_brands(nearby_df) > count_unique_brands(candidates_df):
                    shown = ", ".join(nearby_zones[:3]) + ("…" if len(nearby_zones) > 3 else "")
                    relaxation_reasons.append(f"Included nearby Zomato areas ({shown})")
                    candidates_df = nearby_df

        # Step 4b: Broaden Locality to Parent City / Citywide
        if count_unique_brands(candidates_df) < MIN_CANDIDATES_BEFORE_RELAXATION and locality:
            relaxation_reasons.append("Searched citywide (all of Bangalore)")
            mask = build_filter_mask(
                df,
                city=city,
                locality=locality,
                target_cuisines=target_cuisines,
                allowed_budget_tiers=allowed_budgets,
                min_rating=min_rating,
                strict_locality=False,
            )
            candidates_df = df[mask].copy()

        # Step 5: Broaden Cuisines if still insufficient
        if count_unique_brands(candidates_df) < MIN_CANDIDATES_BEFORE_RELAXATION and target_cuisines:
            relaxation_reasons.append("Included other cuisines")
            mask = build_filter_mask(
                df,
                city=city,
                locality=locality,
                target_cuisines=set(),  # All cuisines
                allowed_budget_tiers=allowed_budgets,
                min_rating=min_rating,
                strict_locality=False,
            )
            candidates_df = df[mask].copy()

    # Step 6: Ultimate Fallback (if still 0 candidates, return top-rated in dataset)
    if len(candidates_df) == 0 and not strict and len(df) > 0:
        relaxation_applied = True
        relaxation_reasons.append("Showing the highest-rated restaurants instead")
        candidates_df = df.nlargest(top_k, "rating").copy()

    # Calculate Vectorized Heuristic Scores
    candidates_df["heuristic_score"] = compute_heuristic_score_series(
        candidates_df["rating"], candidates_df["votes"]
    )

    # Tie-Breaking: Votes descending, then closest cost to budget tier midpoint
    target_midpoint = BUDGET_MIDPOINTS.get(preferences.budget_tier, 1000.0)
    candidates_df["_cost_dist"] = (candidates_df["cost_for_two"] - target_midpoint).abs()

    candidates_df = candidates_df.sort_values(
        by=["heuristic_score", "votes", "_cost_dist"],
        ascending=[False, False, True]
    ).drop(columns=["_cost_dist"])

    # Brand Diversity Throttle: Keep only the highest-scoring branch per restaurant brand
    candidates_df["_brand"] = candidates_df["name"].str.lower().str.strip()
    candidates_df = candidates_df.drop_duplicates(subset=["_brand"]).drop(columns=["_brand"])

    # Slice Top K candidates
    top_candidates_df = candidates_df.head(top_k)

    # Convert to Pydantic RestaurantCandidate domain models
    candidate_records = dataframe_to_candidates(top_candidates_df)

    exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return _finish(candidate_records, relaxation_applied, relaxation_reasons, exec_time_ms)


def _finish(candidate_records, relaxation_applied, relaxation_reasons, exec_time_ms):
    relaxation_message = None
    if relaxation_applied and relaxation_reasons:
        relaxation_message = "Search criteria relaxed: " + "; ".join(relaxation_reasons) + "."

    logger.info(
        "Retrieved %d candidates in %.2fms (relaxation=%s)",
        len(candidate_records),
        exec_time_ms,
        relaxation_applied,
    )
    return candidate_records, relaxation_applied, relaxation_message, exec_time_ms


def dataframe_to_candidates(rows_df: pd.DataFrame) -> List[RestaurantCandidate]:
    """Convert dataset rows into RestaurantCandidate models (new columns optional)."""
    candidate_records: List[RestaurantCandidate] = []
    for _, row in rows_df.iterrows():
        cuisines_raw = row["cuisines"]
        if hasattr(cuisines_raw, "__iter__") and not isinstance(cuisines_raw, str):
            cuisines_list = [str(c).strip().lower() for c in cuisines_raw if str(c).strip()]
        else:
            cuisines_list = [str(cuisines_raw).strip().lower()]

        highlights_raw = row.get("highlights", [])
        if hasattr(highlights_raw, "__iter__") and not isinstance(highlights_raw, str):
            highlights_list = [str(h).strip() for h in highlights_raw if str(h).strip()]
        else:
            highlights_list = []

        candidate_records.append(
            RestaurantCandidate(
                restaurant_id=str(row["restaurant_id"]),
                name=str(row["name"]),
                locality=str(row["locality"]),
                city=str(row["city"]),
                cuisines=cuisines_list,
                cost_for_two=int(row["cost_for_two"]),
                budget_tier=BudgetTier(row["budget_tier"]),
                rating=float(row["rating"]),
                votes=int(row["votes"]),
                highlights=highlights_list,
                is_new=bool(row.get("is_new", False)),
                address=_str_field(row.get("address")),
                phone=_str_field(row.get("phone")),
                zomato_url=_str_field(row.get("zomato_url")),
                rest_type=_str_field(row.get("rest_type")),
                online_order=bool(row.get("online_order", False)),
                book_table=bool(row.get("book_table", False)),
                dining_types=_list_field(row.get("dining_types")),
                review_snippets=_list_field(row.get("review_snippets")),
            )
        )
    return candidate_records
