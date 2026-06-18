"""Local cache (SPEC-CORE-001). DART has a daily quota, so caching is mandatory."""

from .store import CacheStore

__all__ = ["CacheStore"]
