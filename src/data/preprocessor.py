"""Data preprocessing and ETL pipeline for Zomato restaurant data."""
import ast
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


MAX_REVIEW_SNIPPETS = 2
MAX_SNIPPET_CHARS = 180
_MOJIBAKE_MARKERS = ("Ã", "â€", "Â", "ð", "�")


def _is_missing(val: Any) -> bool:
    if val is None:
        return True
    try:
        return bool(pd.isna(val))
    except (TypeError, ValueError):
        return False


def _clean_text(val: Any) -> str:
    """Collapse whitespace; return '' for missing values."""
    if _is_missing(val):
        return ""
    s = re.sub(r"\s+", " ", str(val)).strip()
    return "" if s.lower() == "nan" else s


def _unique_clean_values(values: pd.Series) -> List[str]:
    """Unique, non-empty, order-preserving string values (used in groupby.agg)."""
    seen: List[str] = []
    for v in values:
        s = _clean_text(v)
        if s and s not in seen:
            seen.append(s)
    return seen


def repair_mojibake(val: Any) -> Any:
    """Undo repeated UTF-8-read-as-Latin-1 corruption, e.g. 'CafÃ\\x83Â©' -> 'Café'.

    Re-decodes until the text stops changing or no longer round-trips; text
    that was never corrupted is returned unchanged.
    """
    if not isinstance(val, str) or not any(m in val for m in ("Ã", "Â", "â€")):
        return val
    s = val
    for _ in range(10):
        try:
            fixed = s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if fixed == s:
            break
        s = fixed
    return s


def _yes_no(val: Any) -> bool:
    return _clean_text(val).lower() in ("yes", "true", "1", "y")


def clean_phone(val: Any) -> str:
    """Return the first phone number from a field that may hold several."""
    if _is_missing(val):
        return ""
    # Raw values look like "080 41265000\r\n080 41264000": split on the line
    # breaks / separators *before* normalising whitespace, or the numbers merge.
    for part in re.split(r"[\r\n,/;|]+", str(val)):
        match = re.search(r"\+?\d[\d -]{5,15}\d", part)
        if match:
            number = re.sub(r"\s+", " ", match.group(0)).strip()
            # "00 91..." is the international prefix written out; use "+91..."
            return re.sub(r"^00\s?", "+", number)
    return ""


def clean_url(val: Any) -> str:
    """Keep only https Zomato restaurant URLs, without the tracking query string."""
    s = _clean_text(val)
    if not s.startswith("https://www.zomato.com/"):
        return ""
    return s.split("?", 1)[0]


def _clean_review_text(text: str) -> str:
    text = re.sub(r"^\s*RATED\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    if any(m in text for m in _MOJIBAKE_MARKERS):
        return ""
    if len(text) > MAX_SNIPPET_CHARS:
        cut = text[:MAX_SNIPPET_CHARS].rsplit(" ", 1)[0].rstrip(",.;:!- ")
        text = cut + "…"
    return text


def extract_review_snippets(val: Any, limit: int = MAX_REVIEW_SNIPPETS) -> List[str]:
    """Pick up to `limit` short, readable review snippets, preferring 4★+ reviews.

    Raw values are Python-literal strings: "[('Rated 4.0', 'RATED\\n  Great place...'), ...]".
    """
    s = "" if _is_missing(val) else str(val)
    if len(s) < 10:
        return []
    try:
        reviews = ast.literal_eval(s)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return []
    if not isinstance(reviews, list):
        return []

    scored = []
    for item in reviews:
        if not (isinstance(item, (list, tuple)) and len(item) == 2):
            continue
        rating_match = re.search(r"(\d+(\.\d+)?)", str(item[0]))
        rating = float(rating_match.group(1)) if rating_match else 0.0
        text = _clean_review_text(str(item[1]))
        if len(text) >= 40:
            scored.append((rating, text))

    # Highest-rated first; stable order otherwise
    scored.sort(key=lambda x: -x[0])
    snippets: List[str] = []
    for _, text in scored:
        if text not in snippets:
            snippets.append(text)
        if len(snippets) >= limit:
            break
    return snippets


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

    # Enrichment fields (optional — absent in minimal/synthetic inputs)
    address_series = extract_series(raw_df, ["address"], default_val="")
    phone_series = extract_series(raw_df, ["phone"], default_val="")
    url_series = extract_series(raw_df, ["url"], default_val="")
    rest_type_series = extract_series(raw_df, ["rest_type"], default_val="")
    online_order_series = extract_series(raw_df, ["online_order"], default_val="")
    book_table_series = extract_series(raw_df, ["book_table"], default_val="")
    dining_type_series = extract_series(raw_df, ["listed_in(type)"], default_val="")
    zone_series = extract_series(raw_df, ["listed_in(city)"], default_val="")
    reviews_series = extract_series(raw_df, ["reviews_list"], default_val="")

    df = pd.DataFrame({
        "name": names,
        "locality": localities,
        "city": cities,
        "raw_rate": raw_rates,
        "raw_cost": raw_costs,
        "votes": votes_series,
        "cuisines": cuisines_series,
        "raw_highlights": highlights_series,
        "address": address_series.values,
        "raw_phone": phone_series.values,
        "raw_url": url_series.values,
        "rest_type": rest_type_series.values,
        "raw_online_order": online_order_series.values,
        "raw_book_table": book_table_series.values,
        "raw_dining_type": dining_type_series.values,
        "raw_zone": zone_series.values,
        "raw_reviews": reviews_series.values,
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

    # The raw data repeats a restaurant once per listing (zone x dining type).
    # Collect those listings before de-duplicating so no information is lost.
    df["norm_name"] = df["name"].str.lower()
    df["norm_loc"] = df["locality"].str.lower()
    grouped = df.groupby(["norm_name", "norm_loc"], sort=False)
    dining_types = grouped["raw_dining_type"].agg(_unique_clean_values)
    zones = grouped["raw_zone"].agg(_unique_clean_values)

    # Deduplicate by normalized name and locality (first occurrence wins, so
    # restaurant IDs stay stable across ETL runs)
    df = df.drop_duplicates(subset=["norm_name", "norm_loc"])
    keys = list(zip(df["norm_name"], df["norm_loc"]))
    df["dining_types"] = [dining_types.get(k, []) for k in keys]
    df["zones"] = [zones.get(k, []) for k in keys]
    df = df.drop(columns=["norm_name", "norm_loc"])

    # Repair double/triple-encoded UTF-8 ("CafÃ\x83Â©" -> "Café"). Done after
    # de-duplication so the dedup keys, and therefore restaurant IDs, are unchanged.
    df["name"] = df["name"].apply(repair_mojibake)

    # Enrichment fields (parsed after de-duplication: reviews are expensive)
    df["address"] = df["address"].apply(_clean_text).apply(repair_mojibake)
    df["phone"] = df["raw_phone"].apply(clean_phone)
    df["zomato_url"] = df["raw_url"].apply(clean_url)
    df["rest_type"] = df["rest_type"].apply(_clean_text)
    df["online_order"] = df["raw_online_order"].apply(_yes_no)
    df["book_table"] = df["raw_book_table"].apply(_yes_no)
    df["review_snippets"] = df["raw_reviews"].apply(extract_review_snippets)

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
        "address",
        "phone",
        "zomato_url",
        "rest_type",
        "online_order",
        "book_table",
        "dining_types",
        "zones",
        "review_snippets",
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
