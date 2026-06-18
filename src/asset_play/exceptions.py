"""Exception hierarchy for asset-play.

Kept deliberately small. The important distinctions for callers are:
- ``QuotaExceededError`` — back off / stop, but preserve partial results (CORE AC-4).
- ``InvariantViolation`` — a TRUST invariant was broken (e.g. consolidated FS used
  where separate FS is required). Should never be swallowed silently.
"""

from __future__ import annotations


class AssetPlayError(Exception):
    """Base class for all asset-play errors."""


class ConfigError(AssetPlayError):
    """Configuration is missing or invalid (e.g. required API key absent)."""


class SourceError(AssetPlayError):
    """An external data source failed."""


class RateLimitError(SourceError):
    """Transient rate-limit; retry with backoff is appropriate."""


class QuotaExceededError(SourceError):
    """Hard daily/usage quota hit. Stop calling; preserve partial results."""


class ParseError(AssetPlayError):
    """Could not parse an external payload (financial note, address, etc.)."""


class InvariantViolation(AssetPlayError):
    """A TRUST invariant was violated and the result would be meaningless."""
