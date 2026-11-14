"""In-memory per-client rate limiting for the LLM-backed recommendation endpoint.

Each call to /api/v1/recommend costs a Groq request, so a public deployment
needs a basic guard against a single client burning through API credits.

Design notes:
- Sliding 60-second window per client, stored in process memory. This is
  enough for a single Railway instance; with several replicas each replica
  enforces its own limit (use Redis or similar if you scale out).
- The client is identified by the first address in X-Forwarded-For (set by
  Vercel and Railway's proxies), falling back to the socket peer address.
  X-Forwarded-For can be forged by a client that calls the backend directly,
  so treat this as cost protection, not a security boundary.
- RATE_LIMIT_PER_MINUTE=0 disables the limiter.
"""
import math
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request

from config.settings import settings

WINDOW_SECONDS = 60.0


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window limiter keyed by client identifier."""

    def __init__(self, window_seconds: float = WINDOW_SECONDS):
        self.window_seconds = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = float("-inf")

    def check(self, key: str, limit: int, now: Optional[float] = None) -> Optional[int]:
        """Record a hit for ``key``.

        Returns None if the request is allowed, otherwise the number of seconds
        the client should wait before retrying.
        """
        if limit <= 0:
            return None
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds

        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= limit:
                retry_after = max(1, math.ceil(hits[0] + self.window_seconds - now))
                return retry_after

            hits.append(now)
            self._maybe_sweep(now, cutoff)
            return None

    def _maybe_sweep(self, now: float, cutoff: float) -> None:
        """Drop idle clients occasionally so memory stays bounded."""
        if now - self._last_sweep < self.window_seconds:
            return
        self._last_sweep = now
        idle = [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]
        for k in idle:
            del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


recommend_limiter = SlidingWindowRateLimiter()


def client_identifier(request: Request) -> str:
    """Best-effort client IP behind the Vercel / Railway proxies."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def enforce_recommend_rate_limit(request: Request) -> None:
    """FastAPI dependency: raise 429 when a client exceeds RATE_LIMIT_PER_MINUTE."""
    retry_after = recommend_limiter.check(client_identifier(request), settings.RATE_LIMIT_PER_MINUTE)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "message": f"Too many requests. Please wait {retry_after} seconds and try again.",
            },
            headers={"Retry-After": str(retry_after)},
        )
