"""Shared pytest fixtures."""
import pytest

from src.api.rate_limit import recommend_limiter


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Start every test with an empty rate-limit window.

    All TestClient requests share one client address, so without this the
    suite's many /api/v1/recommend calls could trip the per-minute limit.
    """
    recommend_limiter.reset()
    yield
    recommend_limiter.reset()
