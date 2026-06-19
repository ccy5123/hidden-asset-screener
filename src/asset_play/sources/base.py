"""Shared HTTP machinery for sources: caching, retry/backoff, quota (SPEC-CORE-001).

Design for testability: the network call goes through ``self.session.get(...)``. Tests
inject a fake session, so no real request is made and the cache/quota/backoff behaviour
can be asserted deterministically.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional, Protocol

from ..cache import CacheStore
from ..config import Config
from ..exceptions import QuotaExceededError, RateLimitError, SourceError
from .recorder import active_recorder, preview_text, record


class _Response(Protocol):
    status_code: int

    def json(self) -> Any: ...

    @property
    def content(self) -> bytes: ...

    @property
    def text(self) -> str: ...


class _Session(Protocol):
    def get(self, url: str, params: Optional[dict] = None, timeout: Optional[float] = None) -> _Response: ...


class QuotaTracker:
    """Counts external calls against a daily limit (e.g. DART). Thread-naive on purpose."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.count = 0

    def check(self) -> None:
        if self.count >= self.limit:
            raise QuotaExceededError(
                f"daily quota exhausted ({self.count}/{self.limit}); "
                "stop calling and preserve partial results"
            )

    def increment(self) -> None:
        self.count += 1


class HttpSource:
    """Base for HTTP-backed sources with cache + exponential backoff + quota."""

    source_name: str = "http"

    def __init__(
        self,
        config: Optional[Config] = None,
        *,
        cache: Optional[CacheStore] = None,
        session: Optional[_Session] = None,
        sleep: Callable[[float], None] = time.sleep,
        quota: Optional[QuotaTracker] = None,
    ) -> None:
        self.config = config or Config()
        self.cache = cache
        self._session = session
        self.sleep = sleep
        self.quota = quota

    @property
    def session(self) -> _Session:
        if self._session is None:
            import requests  # imported lazily so tests need no network stack

            session = requests.Session()
            # Some public-data WAFs reject the default python-requests UA.
            session.headers.update({"User-Agent": "asset-play/0.1 (+https://github.com)"})
            self._session = session
        return self._session

    # -- low level -------------------------------------------------------- #
    def _request(self, url: str, params: Optional[dict] = None) -> _Response:
        """GET with retry on transient errors (429/5xx/connection). Honours quota."""
        retries = self.config.max_retries
        base = self.config.backoff_base_seconds
        last_exc: Optional[Exception] = None

        for attempt in range(retries + 1):
            if self.quota is not None:
                self.quota.check()  # raises QuotaExceededError (no retry)
            try:
                resp = self.session.get(
                    url, params=params, timeout=self.config.request_timeout_seconds
                )
            except QuotaExceededError:
                raise
            except Exception as exc:  # connection/timeout — retry
                last_exc = exc
                if attempt < retries:
                    self.sleep(base * (2 ** attempt))
                    continue
                raise SourceError(f"request failed after {retries} retries: {url}") from exc

            if self.quota is not None:
                self.quota.increment()

            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = RateLimitError(f"HTTP {resp.status_code} from {url}")
                if attempt < retries:
                    self.sleep(base * (2 ** attempt))
                    continue
                raise last_exc
            if resp.status_code != 200:
                raise SourceError(f"HTTP {resp.status_code} from {url}")
            self._last_status = resp.status_code  # API 원문 기록용(get_json/get_bytes에서 참조)
            return resp

        # Unreachable, but keep type-checkers happy.
        raise SourceError(str(last_exc) if last_exc else f"request failed: {url}")

    def get_json(
        self,
        url: str,
        params: Optional[dict] = None,
        *,
        namespace: Optional[str] = None,
        cache_key: Optional[str] = None,
        ttl: Optional[float] = None,
    ) -> Any:
        """Cached JSON GET. A cache hit performs **no** external call (CORE AC-2)."""
        use_cache = self.cache is not None and namespace and cache_key
        rec_on = active_recorder() is not None
        if use_cache:
            cached = self.cache.get_json(namespace, cache_key)
            if cached is not None:
                if rec_on:
                    record(self.source_name, url, params=params, status=None,
                           cache_hit=True, preview=preview_text(cached))
                return cached
        t0 = time.perf_counter()
        try:
            data = self._request(url, params).json()
        except Exception as exc:
            if rec_on:
                record(self.source_name, url, params=params,
                       status=getattr(self, "_last_status", None),
                       elapsed_ms=(time.perf_counter() - t0) * 1000, ok=False,
                       preview=f"ERROR: {type(exc).__name__}: {exc}")
            raise
        if rec_on:
            record(self.source_name, url, params=params,
                   status=getattr(self, "_last_status", None),
                   elapsed_ms=(time.perf_counter() - t0) * 1000, preview=preview_text(data))
        if use_cache:
            self.cache.set_json(
                namespace,
                cache_key,
                data,
                ttl if ttl is not None else self.config.cache_ttl_seconds,
            )
        return data

    def get_bytes(self, url: str, params: Optional[dict] = None) -> bytes:
        rec_on = active_recorder() is not None
        t0 = time.perf_counter()
        try:
            content = self._request(url, params).content
        except Exception as exc:
            if rec_on:
                record(self.source_name, url, params=params,
                       status=getattr(self, "_last_status", None),
                       elapsed_ms=(time.perf_counter() - t0) * 1000, ok=False,
                       preview=f"ERROR: {type(exc).__name__}: {exc}")
            raise
        if rec_on:
            record(self.source_name, url, params=params,
                   status=getattr(self, "_last_status", None),
                   elapsed_ms=(time.perf_counter() - t0) * 1000, preview=preview_text(content))
        return content
