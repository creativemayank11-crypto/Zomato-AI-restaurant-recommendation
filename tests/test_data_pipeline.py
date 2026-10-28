"""Unit tests for Phase 1 Data Ingestion and ETL Preprocessing Pipeline."""
import math
import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from config.constants import BudgetTier
from src.data.preprocessor import (
    clean_rating,
    clean_cost,
    clean_cuisines,
    assign_budget_tier,
    clean_zomato_dataset,
    save_processed_data,
    load_processed_data,
)
from src.data.loader import SAMPLE_DATASET_FALLBACK, download_zomato_dataset, load_raw_dataset


def test_clean_rating_standard():
    """Verify standard ratings parsing."""
    rate, is_new = clean_rating("4.2/5")
    assert rate == pytest.approx(4.2)
    assert is_new is False

    rate2, is_new2 = clean_rating("3.8")
    assert rate2 == pytest.approx(3.8)
    assert is_new2 is False


def test_clean_rating_edge_cases():
    """Verify non-numeric tokens ('NEW', '-', None) handling."""
    rate_new, is_new = clean_rating("NEW")
    assert math.isnan(rate_new)
    assert is_new is True

    rate_dash, is_dash = clean_rating("-")
    assert math.isnan(rate_dash)
    assert is_dash is True

    rate_none, is_none = clean_rating(None)
    assert math.isnan(rate_none)
    assert is_none is False


def test_clean_cost():
    """Verify string cost parsing and stripping non-numeric tokens."""
    assert clean_cost("1,500") == 1500
    assert clean_cost("₹ 450 for two") == 450
    assert clean_cost("800") == 800
    assert clean_cost(None) is None
    assert clean_cost("0") is None


def test_clean_cuisines():
    """Verify cuisine normalization and trimming."""
    cuisines = clean_cuisines("Italian, Continental, Desserts")
    assert cuisines == ["italian", "continental", "desserts"]

    empty_cuisines = clean_cuisines("")
    assert empty_cuisines == ["casual dining"]

    none_cuisines = clean_cuisines(None)
    assert none_cuisines == ["casual dining"]


def test_assign_budget_tier():
    """Verify budget tier assignments."""
    assert assign_budget_tier(350) == BudgetTier.LOW
    assert assign_budget_tier(500) == BudgetTier.MEDIUM
    assert assign_budget_tier(1200) == BudgetTier.MEDIUM
    assert assign_budget_tier(1500) == BudgetTier.MEDIUM
    assert assign_budget_tier(2000) == BudgetTier.HIGH


def test_clean_zomato_dataset_pipeline():
    """Test full ETL pipeline on dirty raw dataframe."""
    dirty_data = pd.DataFrame([
        {
            "name": " Cafe Coffee Day ",
            "rate": "3.8/5",
            "votes": "450",
            "location": "MG Road",
            "cuisines": "Cafe, Beverages",
            "approx_cost(for two people)": "600",
            "listed_in(city)": "Bengaluru",
        },
        {
            "name": "New Pizzeria",
            "rate": "NEW",
            "votes": "0",
            "location": "Indiranagar",
            "cuisines": "Pizza, Fast Food",
            "approx_cost(for two people)": "400",
            "listed_in(city)": "Bangalore",
        },
        {
            "name": "Missing Cost Diner",
            "rate": "4.5/5",
            "votes": "1200",
            "location": "Koramangala",
            "cuisines": "Continental",
            "approx_cost(for two people)": None,
            "listed_in(city)": "Bangalore",
        },
        {
            # Should be dropped: missing name
            "name": None,
            "rate": "4.0/5",
            "location": "Koramangala",
        },
        {
            # Duplicate entry: same name and locality
            "name": "Cafe Coffee Day",
            "rate": "3.8/5",
            "votes": "450",
            "location": "MG Road",
            "listed_in(city)": "Bangalore",
        },
    ])

    cleaned_df = clean_zomato_dataset(dirty_data)

    # 1. Assertions on row count (1 dropped for null name, 1 duplicate removed -> 3 rows)
    assert len(cleaned_df) == 3

    # 2. Assert zero nulls in critical columns
    for col in ["restaurant_id", "name", "city", "rating", "cost_for_two", "budget_tier"]:
        assert cleaned_df[col].isnull().sum() == 0, f"Column {col} has null values"

    # 3. Assert rating bounds
    assert (cleaned_df["rating"] >= 1.0).all()
    assert (cleaned_df["rating"] <= 5.0).all()

    # 4. Assert restaurant_id pattern
    assert cleaned_df["restaurant_id"].iloc[0] == "ZOM_00001"
    assert cleaned_df["restaurant_id"].iloc[1] == "ZOM_00002"

    # 5. Assert city alias normalization (Bengaluru -> Bangalore)
    assert cleaned_df["city"].iloc[0] == "Bangalore"


def test_parquet_roundtrip(tmp_path: Path):
    """Test saving and loading DataFrame from Parquet format."""
    sample_df = pd.DataFrame(SAMPLE_DATASET_FALLBACK)
    clean_df = clean_zomato_dataset(sample_df)

    parquet_file = tmp_path / "test_zomato_clean.parquet"
    saved_path = save_processed_data(clean_df, parquet_file)
    assert saved_path.exists()

    loaded_df = load_processed_data(parquet_file)
    assert len(loaded_df) == len(clean_df)
    assert list(loaded_df.columns) == list(clean_df.columns)
    assert loaded_df["name"].iloc[0] == clean_df["name"].iloc[0]
