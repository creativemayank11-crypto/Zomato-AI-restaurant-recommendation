"""Executable script to run Phase 1 ETL pipeline: download, clean, and cache dataset."""
import sys
import logging
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.loader import download_zomato_dataset, load_raw_dataset
from src.data.preprocessor import clean_zomato_dataset, save_processed_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_etl")


def main():
    logger.info("=== Starting Phase 1 Data Ingestion & ETL Pipeline ===")
    
    # 1. Download / Load raw dataset
    raw_path = download_zomato_dataset()
    logger.info("Raw dataset ready at: %s", raw_path)
    
    raw_df = load_raw_dataset(raw_path)
    logger.info("Loaded %d raw records", len(raw_df))
    
    # 2. Clean and preprocess
    clean_df = clean_zomato_dataset(raw_df)
    
    # 3. Save to Parquet
    parquet_path = save_processed_data(clean_df)
    logger.info("Clean dataset successfully serialized to: %s", parquet_path)
    logger.info("ETL Summary: %d clean restaurants across %d cities", len(clean_df), clean_df["city"].nunique())
    print(f"\n[SUCCESS] Processed {len(clean_df)} restaurants saved to {parquet_path}")


if __name__ == "__main__":
    main()
