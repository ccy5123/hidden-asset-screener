"""External data sources (SPEC-CORE-001).

All clients are constructed with an injectable ``session``/``transport`` so tests run
without network access, and share the retry/backoff/quota machinery in ``base``.
"""

from .base import HttpSource, QuotaTracker
from .dart_client import DartClient, classify_land_measurement_model
from .krx import KrxClient, PriceProvider, StaticPriceProvider

__all__ = [
    "HttpSource",
    "QuotaTracker",
    "DartClient",
    "classify_land_measurement_model",
    "KrxClient",
    "PriceProvider",
    "StaticPriceProvider",
]
