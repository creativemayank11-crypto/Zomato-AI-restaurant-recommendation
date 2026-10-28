"""Dependency injection: dataset singleton and Groq LLM client singleton."""
import logging
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (populated during FastAPI lifespan startup)
# ---------------------------------------------------------------------------
_dataset: Optional[pd.DataFrame] = None
_llm_client: Optional[Any] = None
_llm_provider: str = "groq"


def get_dataset() -> pd.DataFrame:
    """Return the in-memory Parquet dataset singleton.
    
    Raises RuntimeError if the dataset was not loaded during startup.
    """
    if _dataset is None:
        raise RuntimeError("Dataset not loaded. Ensure the FastAPI lifespan startup has run.")
    return _dataset


def get_llm_client() -> Optional[Any]:
    """Return the LLM client singleton (may be None in deterministic-only mode)."""
    return _llm_client


def get_llm_provider() -> str:
    """Return the active LLM provider name."""
    return _llm_provider


def load_dataset_singleton() -> pd.DataFrame:
    """Load the processed Parquet dataset into the module-level singleton."""
    global _dataset
    from src.data.preprocessor import load_processed_data
    _dataset = load_processed_data()
    logger.info("Dataset loaded: %d restaurants", len(_dataset))
    return _dataset


def init_llm_client_singleton() -> tuple[Optional[Any], str]:
    """Initialise the Groq LLM client singleton (or None if key is absent)."""
    global _llm_client, _llm_provider
    from config.settings import settings

    provider = settings.DEFAULT_LLM_PROVIDER.strip().lower()
    _llm_provider = provider

    if provider == "groq":
        if settings.GROQ_API_KEY:
            from groq import Groq
            _llm_client = Groq(api_key=settings.GROQ_API_KEY)
            logger.info("Groq client initialised (model: %s)", settings.GROQ_MODEL)
        else:
            _llm_client = None
            logger.warning(
                "GROQ_API_KEY not set — operating in deterministic (no-LLM) mode."
            )
    elif provider == "gemini":
        if settings.GEMINI_API_KEY:
            from google import genai
            _llm_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            logger.info("Gemini client initialised (model: %s)", settings.GEMINI_MODEL)
        else:
            _llm_client = None
            logger.warning("GEMINI_API_KEY not set — deterministic mode.")
    elif provider in ("openai", "gpt"):
        if settings.OPENAI_API_KEY:
            from openai import OpenAI
            _llm_client = OpenAI(api_key=settings.OPENAI_API_KEY)
            logger.info("OpenAI client initialised (model: %s)", settings.OPENAI_MODEL)
        else:
            _llm_client = None
            logger.warning("OPENAI_API_KEY not set — deterministic mode.")
    else:
        _llm_client = None
        logger.warning("Unknown LLM provider '%s' — deterministic mode.", provider)

    return _llm_client, provider


def release_dataset_singleton() -> None:
    """Release the dataset singleton on application shutdown."""
    global _dataset
    _dataset = None
    logger.info("Dataset singleton released.")
