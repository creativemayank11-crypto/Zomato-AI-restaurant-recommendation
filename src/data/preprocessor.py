"""Data preprocessing and ETL pipeline for Zomato restaurant data."""
import re
import logging
from pathlib import Path
from typing import Any, List, Optional, Tuple
import numpy as np
import pandas as pd

from config.constants import BudgetTier, BUDGET_BOUNDARIES, CITY_ALIASES
from config.settings import settings

logger = logging.getLogger(__name__)


def clean_rating(val: Any) -> Tuple[float, bool]:
    """Clean rating string (e.g., '4.1/5', 'NEW', '-') into float and is_new flag.
    
    Returns:
        Tuple[float, bool]: (cleaned_rating, is_new_restaurant)
    """
    if pd.isna(val) or val is None:
        return np.nan, False

    s = str(val).strip()
    if s.upper() in ("NEW", "-", "OPENING SOON", ""):
        return np.nan, True

    match = re.search(r"(\d+(\.\d+)?)", s)
    if match:
        try:
            r = float(match.group(1))
            if 1.0 <= r <= 5.0:
                return r, False
        except ValueError:
            pass

    return np.nan, False


def clean_cost(val: Any) -> Optional[int]:
    """Extract integer cost for two from strings like '1,200' or '₹500 for two'."""
    if pd.isna(val) or val is None:
        return None

    digits = re.sub(r"[^\d]", "", str(val))
    if digits:
        cost = int(digits)
        return cost if cost > 0 else None
    return None


def clean_cuisines(val: Any) -> List[str]:
    """Convert comma-separated cuisine string into a cleaned list of lowercased tokens."""
    if pd.isna(val) or val is None:
        return ["casual dining"]

    tokens = [c.strip().lower() for c in str(val).split(",") if c.strip()]
    return tokens if tokens else ["casual dining"]


def assign_budget_tier(cost: int) -> BudgetTier:
    """Classify cost for two into Low (< ₹500), Medium (₹500 - ₹1500), or High (> ₹1500)."""
    if cost < BUDGET_BOUNDARIES[BudgetTier.LOW]["max"]:
        return BudgetTier.LOW
    elif cost <= BUDGET_BOUNDARIES[BudgetTier.MEDIUM]["max"]:
        return BudgetTier.MEDIUM
    else:
        return BudgetTier.HIGH


def extract_series(df: pd.DataFrame, candidates: List[str], default_val: Any = None) -> pd.Series:
    """Safely extract a Series from DataFrame matching any candidate name."""
    for name in candidates:
        if name in df.columns:
            s = df[name]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            return s.copy()
    return pd.Series([default_val] * len(df))


def clean_zomato_dataset(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Execute end-to-end cleaning, normalization, imputation, and feature extraction."""
    logger.info("Starting ETL processing on raw dataset with %d rows", len(raw_df))
    
    # Extract series safely without column name collision
    names = extract_series(raw_df, ["name", "restaurant_name"], default_val="")
    localities = extract_series(raw_df, ["location", "locality", "address"], default_val="City Center")
    cities = extract_series(raw_df, ["city", "listed_in(city)"], default_val="Bangalore")
    raw_rates = extract_series(raw_df, ["rate", "rating", "aggregate_rating"], default_val="3.8")
    raw_costs = extract_series(raw_df, ["approx_cost(for two people)", "cost_for_two", "cost"], default_val="800")
    votes_series = extract_series(raw_df, ["votes"], default_val=100)
    cuisines_series = extract_series(raw_df, ["cuisines", "cuisine"], default_val="Casual Dining")
    highlights_series = extract_series(raw_df, ["dish_liked", "rest_type", "highlights"], default_val="")

    df = pd.DataFrame({
        "name": names,
        "locality": localities,
        "city": cities,
        "raw_rate": raw_rates,
        "raw_cost": raw_costs,
        "votes": votes_series,
        "cuisines": cuisines_series,
        "raw_highlights": highlights_series,
    })

    # Drop entries with missing restaurant names
    df = df.dropna(subset=["name"])
    df["name"] = df["name"].astype(str).str.strip()
    df = df[df["name"] != ""]
    df = df[df["name"].str.lower() != "nan"]

    # Normalize localities
    df["locality"] = df["locality"].fillna("City Center").astype(str).str.strip()

    # Normalize cities:
    # If the dataset city is a Bangalore locality or listed_in(city) is Bangalore neighborhood,
    # map to Bangalore, while preserving other cities like Delhi, Mumbai, Hyderabad.
    bangalore_zones = {
        "banashankari", "bannerghatta road", "basavanagudi", "bellandur", "brigade road",
        "brookefield", "btm", "church street", "electronic city", "frazer town", "hsr",
        "indiranagar", "jayanagar", "jp nagar", "kalyan nagar", "kammanahalli",
        "koramangala 4th block", "koramangala 5th block", "koramangala 6th block",
        "koramangala 7th block", "lavelle road", "malleshwaram", "marathahalli", "mg road",
        "new bel road", "old airport road", "rajajinagar", "residency road", "sarjapur road",
        "whitefield", "bengaluru", "bangalore"
    }

    def resolve_city(c_val: Any) -> str:
        s = str(c_val).strip().lower()
        if s in bangalore_zones:
            return "Bangalore"
        clean = CITY_ALIASES.get(s, s)
        return clean.title()

    df["city"] = df["city"].apply(resolve_city)

    # Clean rating and track new restaurants
    rating_tuples = df["raw_rate"].apply(clean_rating)
    df["rating"] = [r[0] for r in rating_tuples]
    df["is_new"] = [r[1] for r in rating_tuples]

    # Clean cost
    df["cost_for_two"] = df["raw_cost"].apply(clean_cost)

    # Impute missing ratings with median
    overall_median_rating = df["rating"].median()
    if pd.isna(overall_median_rating):
        overall_median_rating = 3.8
    df["rating"] = df["rating"].fillna(overall_median_rating)

    # Impute missing cost with median
    overall_median_cost = df["cost_for_two"].median()
    if pd.isna(overall_median_cost) or overall_median_cost == 0:
        overall_median_cost = 750
    df["cost_for_two"] = df["cost_for_two"].fillna(int(overall_median_cost)).astype(int)

    # Clean votes
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0).astype(int)

    # Clean cuisines
    df["cuisines"] = df["cuisines"].apply(clean_cuisines)

    # Assign budget tier
    df["budget_tier"] = df["cost_for_two"].apply(lambda c: assign_budget_tier(c).value)

    # Extract highlights / features
    def parse_highlights(val: Any) -> List[str]:
        if pd.isna(val) or val is None or not str(val).strip():
            return []
        items = [t.strip() for t in str(val).split(",") if t.strip()]
        return items[:6]  # Keep top 6 features to avoid bloat

    df["highlights"] = df["raw_highlights"].apply(parse_highlights)

    # Deduplicate by normalized name and locality
    df["norm_name"] = df["name"].str.lower()
    df["norm_loc"] = df["locality"].str.lower()
    df = df.drop_duplicates(subset=["norm_name", "norm_loc"]).drop(columns=["norm_name", "norm_loc"])

    # Generate canonical restaurant_id (e.g. ZOM_00001)
    df = df.reset_index(drop=True)
    df["restaurant_id"] = [f"ZOM_{i+1:05d}" for i in range(len(df))]

    # Select canonical columns
    canonical_cols = [
        "restaurant_id",
        "name",
        "locality",
        "city",
        "cuisines",
        "cost_for_two",
        "budget_tier",
        "rating",
        "votes",
        "highlights",
        "is_new",
    ]
    result_df = df[canonical_cols]
    logger.info("ETL complete. Cleaned dataset has %d unique records", len(result_df))
    return result_df


def save_processed_data(df: pd.DataFrame, output_path: Optional[Path] = None) -> Path:
    """Save cleaned DataFrame to Parquet format."""
    destination = output_path or settings.PROCESSED_DATA_PATH
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(destination, index=False, engine="pyarrow")
    logger.info("Saved processed dataset to %s (%d records)", destination, len(df))
    return destination


def load_processed_data(path: Optional[Path] = None) -> pd.DataFrame:
    """Load cleaned Parquet dataset into a pandas DataFrame."""
    target_path = path or settings.PROCESSED_DATA_PATH
    target_path = Path(target_path)
    if not target_path.exists():
        raise FileNotFoundError(f"Processed dataset not found at {target_path}. Run ETL pipeline first.")
    return pd.read_parquet(target_path, engine="pyarrow")
