# -----------------------------------------------------------------------------
# File: utils/data_sources/base_client.py
"""
BaseClient: Shared infrastructure for API clients
- Singleton aiohttp.ClientSession (connection pooling)
- In-memory TTL cache with periodic cleanup
- asyncio.Lock for safety
- Retry with exponential backoff
- API key validation & masking helpers
"""
from __future__ import annotations

import asyncio
import aiohttp
import time
import logging
import re
from typing import Any, Dict, Optional, Tuple, Callable

_LOG = logging.getLogger(__name__)


class BaseClient:
    """Base client providing session management, cache, locking and helpers.

    Notes:
        - Use subclassing. Subclasses should call `await self._request(...)`
        - Designed to be safe to import in multi-user bot contexts.
    """

    _session: Optional[aiohttp.ClientSession] = None
    _session_lock = asyncio.Lock()
    _cache: Dict[str, Tuple[Any, float]] = {}
    _cache_ttl: int = 300  # seconds
    _cleanup_task: Optional[asyncio.Task] = None

    def __init__(self, api_key: Optional[str] = None, cache_ttl: Optional[int] = None):
        self.api_key = api_key
        if cache_ttl is not None:
            self._cache_ttl = cache_ttl

        # validate api key format if provided
        if self.api_key is not None:
            if not self._validate_api_key(self.api_key):
                raise ValueError("Invalid API key format")

        # ensure cleanup task running
        if not BaseClient._cleanup_task:
            try:
                BaseClient._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            except RuntimeError:
                # if event loop not running at import-time, skip creating task
                _LOG.debug("Event loop not running; cleanup task deferred")

    @classmethod
    async def _ensure_session(cls) -> aiohttp.ClientSession:
        """Return a singleton aiohttp ClientSession (connection pooling).
        Safe to call concurrently.
        """
        async with cls._session_lock:
            if cls._session is None or cls._session.closed:
                timeout = aiohttp.ClientTimeout(total=30)
                cls._session = aiohttp.ClientSession(timeout=timeout)
            return cls._session

    @staticmethod
    def _validate_api_key(key: str) -> bool:
        # conservative default rule: alnum, underscore, hyphen, length >= 20
        return bool(re.match(r"^[A-Za-z0-9_\-]{20,}$", key))

    @staticmethod
    def mask_key(key: str) -> str:
        if not key:
            return ""
        return "****" + key[-4:]

    @classmethod
    def _cache_get(cls, key: str) -> Optional[Any]:
        val = cls._cache.get(key)
        if not val:
            return None
        data, t = val
        if time.time() - t > cls._cache_ttl:
            cls._cache.pop(key, None)
            return None
        return data

    @classmethod
    def _cache_set(cls, key: str, data: Any) -> None:
        cls._cache[key] = (data, time.time())

    @classmethod
    async def _periodic_cleanup(cls) -> None:
        while True:
            try:
                now = time.time()
                expired = [k for k, (_, t) in cls._cache.items() if now - t > cls._cache_ttl]
                for k in expired:
                    cls._cache.pop(k, None)
                await asyncio.sleep(max(60, cls._cache_ttl // 2))
            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOG.exception("Cache cleanup failed: %s", e)
                await asyncio.sleep(60)

    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        cache: bool = True,
        cache_key: Optional[str] = None,
        timeout: int = 15,
        retry: int = 3,
        backoff: float = 0.5,
        parse_json: bool = True,
    ) -> Optional[Any]:
        """Robust HTTP request wrapper with caching, retries and basic error handling.

        Args:
            method: HTTP method (GET/POST)
            url: full URL
            params: query params
            headers: request headers
            cache: whether to use cache
            cache_key: explicit cache key
            timeout: per-request timeout
            retry: number of retries
            backoff: base backoff seconds
            parse_json: whether to call resp.json() or resp.text()
        """
        key = cache_key or f"{method}:{url}:{params}"
        if cache:
            cached = self._cache_get(key)
            if cached is not None:
                return cached

        session = await self._ensure_session()
        attempt = 0
        while attempt < retry:
            try:
                async with session.request(method, url, params=params, headers=headers, timeout=timeout) as resp:
                    if resp.status >= 500:
                        _LOG.warning("Server error %s %s", resp.status, url)
                        attempt += 1
                        await asyncio.sleep(backoff * (2 ** attempt))
                        continue
                    if resp.status == 429:
                        # rate limit: read Retry-After if present
                        retry_after = resp.headers.get("Retry-After")
                        wait = int(retry_after) if retry_after and retry_after.isdigit() else backoff * (2 ** attempt)
                        _LOG.warning("Rate limited; sleeping %s", wait)
                        await asyncio.sleep(wait)
                        attempt += 1
                        continue
                    if resp.status >= 400:
                        text = await resp.text()
                        _LOG.warning("HTTP %s for %s: %s", resp.status, url, text[:200])
                        return None

                    if parse_json:
                        data = await resp.json()
                    else:
                        data = await resp.text()

                    if cache:
                        self._cache_set(key, data)
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                _LOG.warning("Request error %s %s: %s", method, url, e)
                attempt += 1
                await asyncio.sleep(backoff * (2 ** attempt))
            except Exception as e:  # pragma: no cover - safety
                _LOG.exception("Unexpected error during request: %s", e)
                return None
        _LOG.error("Failed after %s attempts: %s %s", retry, method, url)
        return None

