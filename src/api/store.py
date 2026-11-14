"""Small key-value store used for response caching and rate limiting.

Two backends:
- ``UpstashStore``: Upstash Redis over its REST API, shared by every server
  instance. Enabled when ``UPSTASH_REDIS_REST_URL`` and ``UPSTASH_REDIS_REST_TOKEN``
  are set (Vercel's KV / Upstash integration also exposes them as
  ``KV_REST_API_URL`` / ``KV_REST_API_TOKEN``, which are accepted too).
- ``MemoryStore``: per-process memory. The default; fine locally, but on
  serverless each instance has its own copy.

Store errors never fail a request: callers treat them as a cache miss / no limit.
Uses only the standard library (no redis client dependency).
"""
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from config.settings import settings

logger = logging.getLogger(__name__)


class StoreError(Exception):
    """Raised when the backing store cannot be reached or returns an error."""


class MemoryStore:
    """Thread-safe in-process store with per-key expiry."""

    name = "memory"

    def __init__(self, max_keys: int = 5000):
        self._data: Dict[str, Tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def _purge(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._data.items() if exp <= now]
        for k in expired:
            del self._data[k]
        # Bound memory: drop the soonest-expiring keys if still too big
        if len(self._data) > self._max_keys:
            for k, _ in sorted(self._data.items(), key=lambda kv: kv[1][1])[: len(self._data) - self._max_keys]:
                del self._data[k]

    def get(self, key: str) -> Optional[str]:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if not item or item[1] <= now:
                return None
            return item[0]

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        now = time.time()
        with self._lock:
            self._data[key] = (value, now + ttl_seconds)
            if len(self._data) > self._max_keys:
                self._purge(now)

    def incr_window(self, key: str, window_seconds: int) -> int:
        """Increment a fixed-window counter; the window starts at the first hit."""
        now = time.time()
        with self._lock:
            value, exp = self._data.get(key, (0, 0.0))
            if exp <= now:
                value, exp = 0, now + window_seconds
            value = int(value) + 1
            self._data[key] = (value, exp)
            return value

    def ttl(self, key: str) -> int:
        with self._lock:
            item = self._data.get(key)
            return max(0, int(item[1] - time.time())) if item else 0

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class UpstashStore:
    """Upstash Redis via its REST API (https://upstash.com/docs/redis/features/restapi)."""

    name = "upstash"

    def __init__(self, url: str, token: str, timeout: float = 1.5):
        self._url = url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _pipeline(self, commands: List[List[Any]]) -> List[Any]:
        body = json.dumps([[str(part) for part in cmd] for cmd in commands]).encode()
        req = urllib.request.Request(
            f"{self._url}/pipeline",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise StoreError(f"Upstash request failed: {exc}") from exc
        results = []
        for item in payload:
            if isinstance(item, dict) and "error" in item:
                raise StoreError(f"Upstash error: {item['error']}")
            results.append(item.get("result") if isinstance(item, dict) else None)
        return results

    def get(self, key: str) -> Optional[str]:
        return self._pipeline([["GET", key]])[0]

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._pipeline([["SET", key, value, "EX", ttl_seconds]])

    def incr_window(self, key: str, window_seconds: int) -> int:
        # NX: only set the expiry when the key is new, so the window is fixed
        count, _ = self._pipeline([["INCR", key], ["EXPIRE", key, window_seconds, "NX"]])
        return int(count)

    def ttl(self, key: str) -> int:
        value = self._pipeline([["TTL", key]])[0]
        return max(0, int(value or 0))


_store = None
_store_lock = threading.Lock()


def get_store():
    """Return the configured store (created once per process)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                url = settings.UPSTASH_REDIS_REST_URL
                token = settings.UPSTASH_REDIS_REST_TOKEN
                if url and token:
                    _store = UpstashStore(url, token)
                    logger.info("Using Upstash Redis store for cache and rate limits.")
                else:
                    _store = MemoryStore()
                    logger.info("Using in-memory store for cache and rate limits (per instance).")
    return _store


def set_store(store) -> None:
    """Override the store (tests)."""
    global _store
    _store = store
