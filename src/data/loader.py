"""Data loader for downloading and caching the Zomato dataset from Hugging Face."""
import os
import logging
from pathlib import Path
from typing import Optional
import pandas as pd

from config.settings import settings

logger = logging.getLogger(__name__)

HUGGINGFACE_DATASET_ID = "ManikaSaini/zomato-restaurant-recommendation"
HF_DIRECT_CSV_URL = (
    "https://huggingface.co/datasets/ManikaSaini/zomato-restaurant-recommendation/raw/main/zomato.csv"
)

# Realistic fallback sample records in case the environment is completely offline
SAMPLE_DATASET_FALLBACK = [
    {
        "name": "Toscano",
        "rate": "4.5/5",
        "votes": "1250",
        "location": "Indiranagar",
        "rest_type": "Casual Dining",
        "cuisines": "Italian, Continental, Desserts",
        "approx_cost(for two people)": "1,500",
        "listed_in(city)": "Bangalore",
    },
    {
        "name": "The Big Chill Cafe",
        "rate": "4.6/5",
        "votes": "4890",
        "location": "Khan Market",
        "rest_type": "Cafe, Casual Dining",
        "cuisines": "Italian, Continental, Pizza, Desserts",
        "approx_cost(for two people)": "1,600",
        "listed_in(city)": "Delhi",
    },
    {
        "name": "Saravana Bhavan",
        "rate": "4.2/5",
        "votes": "3120",
        "location": "Connaught Place",
        "rest_type": "Quick Bites",
        "cuisines": "South Indian, Fast Food",
        "approx_cost(for two people)": "450",
        "listed_in(city)": "Delhi",
    },
    {
        "name": "Bikanervala",
        "rate": "4.1/5",
        "votes": "1940",
        "location": "Karol Bagh",
        "rest_type": "Quick Bites, Sweet Shop",
        "cuisines": "North Indian, Fast Food, Street Food, Mithai",
        "approx_cost(for two people)": "400",
        "listed_in(city)": "Delhi",
    },
    {
        "name": "Karim's",
        "rate": "4.4/5",
        "votes": "5200",
        "location": "Jama Masjid",
        "rest_type": "Casual Dining",
        "cuisines": "Mughlai, North Indian, Kebab",
        "approx_cost(for two people)": "800",
        "listed_in(city)": "Delhi",
    },
    {
        "name": "Glen's Bakehouse",
        "rate": "4.3/5",
        "votes": "2800",
        "location": "Indiranagar",
        "rest_type": "Bakery, Cafe",
        "cuisines": "Cafe, Bakery, Desserts, Fast Food",
        "approx_cost(for two people)": "600",
        "listed_in(city)": "Bangalore",
    },
    {
        "name": "Vidyarthi Bhavan",
        "rate": "4.4/5",
        "votes": "6100",
        "location": "Basavanagudi",
        "rest_type": "Quick Bites",
        "cuisines": "South Indian",
        "approx_cost(for two people)": "250",
        "listed_in(city)": "Bangalore",
    },
    {
        "name": "Truftles",
        "rate": "4.7/5",
        "votes": "14500",
        "location": "Koramangala 5th Block",
        "rest_type": "Cafe, Casual Dining",
        "cuisines": "Cafe, American, Burger, Steak, Desserts",
        "approx_cost(for two people)": "900",
        "listed_in(city)": "Bangalore",
    },
    {
        "name": "Bawarchi",
        "rate": "4.3/5",
        "votes": "8900",
        "location": "RTC X Roads",
        "rest_type": "Casual Dining",
        "cuisines": "Biryani, North Indian, Mughlai, Chinese",
        "approx_cost(for two people)": "700",
        "listed_in(city)": "Hyderabad",
    },
    {
        "name": "Paradise Biryani",
        "rate": "4.1/5",
        "votes": "7300",
        "location": "Secunderabad",
        "rest_type": "Casual Dining",
        "cuisines": "Biryani, North Indian, Kebab",
        "approx_cost(for two people)": "800",
        "listed_in(city)": "Hyderabad",
    },
    {
        "name": "Britannia & Co.",
        "rate": "4.3/5",
        "votes": "3400",
        "location": "Ballard Estate",
        "rest_type": "Casual Dining",
        "cuisines": "Parsi, Iranian, Fast Food",
        "approx_cost(for two people)": "1,000",
        "listed_in(city)": "Mumbai",
    },
    {
        "name": "Bademiya",
        "rate": "3.9/5",
        "votes": "4100",
        "location": "Colaba",
        "rest_type": "Quick Bites, Casual Dining",
        "cuisines": "Mughlai, North Indian, Street Food, Rolls",
        "approx_cost(for two people)": "600",
        "listed_in(city)": "Mumbai",
    },
    {
        "name": "Corner House Ice Cream",
        "rate": "4.6/5",
        "votes": "6500",
        "location": "Residency Road",
        "rest_type": "Dessert Parlor",
        "cuisines": "Ice Cream, Desserts",
        "approx_cost(for two people)": "350",
        "listed_in(city)": "Bangalore",
    },
    {
        "name": "Mainland China",
        "rate": "4.4/5",
        "votes": "2300",
        "location": "Church Street",
        "rest_type": "Fine Dining",
        "cuisines": "Chinese, Asian, Seafood",
        "approx_cost(for two people)": "1,800",
        "listed_in(city)": "Bangalore",
    },
    {
        "name": "Smoke House Deli",
        "rate": "4.5/5",
        "votes": "3100",
        "location": "Lavelle Road",
        "rest_type": "Casual Dining",
        "cuisines": "European, Italian, Continental, Cafe",
        "approx_cost(for two people)": "2,000",
        "listed_in(city)": "Bangalore",
    },
]


def download_zomato_dataset(
    output_path: Optional[Path] = None, force_download: bool = False
) -> Path:
    """Download Zomato dataset from Hugging Face and save as raw CSV."""
    destination = output_path or settings.RAW_DATA_PATH
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and not force_download and destination.stat().st_size > 500:
        logger.info("Raw dataset already cached at %s", destination)
        return destination

    logger.info("Attempting to download dataset from Hugging Face: %s", HUGGINGFACE_DATASET_ID)

    # Strategy 1: Hugging Face datasets library
    try:
        from datasets import load_dataset
        ds = load_dataset(HUGGINGFACE_DATASET_ID, split="train")
        df = ds.to_pandas()
        df.to_csv(destination, index=False)
        logger.info("Successfully fetched dataset via datasets library (%d rows)", len(df))
        return destination
    except Exception as exc1:
        logger.warning("datasets library download failed (%s). Trying direct CSV read...", exc1)

    # Strategy 2: Direct HTTP CSV read via pandas
    try:
        df = pd.read_csv(HF_DIRECT_CSV_URL)
        df.to_csv(destination, index=False)
        logger.info("Successfully fetched dataset via direct CSV URL (%d rows)", len(df))
        return destination
    except Exception as exc2:
        logger.warning("Direct CSV download failed (%s). Generating fallback sample dataset...", exc2)

    # Strategy 3: Built-in resilient fallback sample
    df = pd.DataFrame(SAMPLE_DATASET_FALLBACK)
    df.to_csv(destination, index=False)
    logger.info("Saved resilient offline dataset to %s (%d rows)", destination, len(df))
    return destination


def load_raw_dataset(path: Optional[Path] = None) -> pd.DataFrame:
    """Load raw dataset into pandas DataFrame, downloading if needed."""
    csv_path = path or settings.RAW_DATA_PATH
    csv_path = Path(csv_path)

    if not csv_path.exists() or csv_path.stat().st_size == 0:
        csv_path = download_zomato_dataset(csv_path)

    return pd.read_csv(csv_path)
