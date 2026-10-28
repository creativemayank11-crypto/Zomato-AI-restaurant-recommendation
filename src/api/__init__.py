"""API module: routes, dependencies, and application factory."""
from src.api.routes import router
from src.api.dependencies import (
    get_dataset,
    get_llm_client,
    get_llm_provider,
)

__all__ = [
    "router",
    "get_dataset",
    "get_llm_client",
    "get_llm_provider",
]
