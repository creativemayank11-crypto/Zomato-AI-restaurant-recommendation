"""Application settings and environment variable management."""
import os
from pathlib import Path
from typing import Optional

try:
    from pydantic_settings import BaseSettings
    from pydantic import Field, ConfigDict
    HAS_PYDANTIC_SETTINGS = True
except ImportError:
    try:
        from pydantic import BaseModel as BaseSettings, Field, ConfigDict
        HAS_PYDANTIC_SETTINGS = False
    except ImportError:
        class BaseSettings:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
        def Field(default=None, **kwargs):
            return default
        ConfigDict = None
        HAS_PYDANTIC_SETTINGS = False

from dotenv import load_dotenv

# Load .env file from project root
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings(BaseSettings):
    """Central application configuration loaded from environment variables."""
    if ConfigDict is not None:
        model_config = ConfigDict(extra="ignore")

    # LLM Provider Configuration (groq | gemini | openai)
    DEFAULT_LLM_PROVIDER: str = os.getenv("DEFAULT_LLM_PROVIDER", "groq")

    # Groq Configuration (Primary LLM provider — sub-second inference via LPU)
    GROQ_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    
    # OpenAI Configuration
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    # Hyperparameters
    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.2"))
    MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "1024"))

    # API App Configuration
    APP_VERSION: str = os.getenv("APP_VERSION", "0.1.0")
    APP_TITLE: str = os.getenv("APP_TITLE", "Zomato AI Recommender API")

    
    # Server Settings
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
    
    # Dataset Storage Paths
    RAW_DATA_PATH: Path = BASE_DIR / os.getenv("RAW_DATA_PATH", "data/raw/zomato_raw.csv")
    PROCESSED_DATA_PATH: Path = BASE_DIR / os.getenv("PROCESSED_DATA_PATH", "data/processed/zomato_clean.parquet")
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# Global singleton settings instance
settings = Settings()
