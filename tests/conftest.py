"""Shared pytest fixtures."""
import pytest

from src.api.rate_limit import recommend_limiter
from src.api.store import MemoryStore, set_store


@pytest.fixture(autouse=True)
def _isolate_state():
    """Start every test with an empty rate-limit window and response cache.

    All TestClient requests share one client address, so without this the
    suite's many /api/v1/recommend calls could trip the per-minute limit, and
    a cached answer from one test could leak into another.
    """
    recommend_limiter.reset()
    set_store(MemoryStore())
    yield
    recommend_limiter.reset()
    set_store(MemoryStore())
