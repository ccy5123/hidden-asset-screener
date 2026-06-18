"""Runtime configuration and tunable assumptions (SPEC §8 open questions).

Loaded from environment variables (``ASSET_PLAY_*``) or constructed directly in tests.
No secret is ever logged.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .domain.enums import Market


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- API keys (all free) ---
    dart_api_key: Optional[str] = None
    data_go_kr_key: Optional[str] = None
    vworld_key: Optional[str] = None

    # --- Tunable assumptions (§8) ---
    # §8.1 corporate tax rate for after-tax net-surplus correction (single-rate model).
    corporate_tax_rate: Decimal = Decimal("0.22")
    # §8.2 공시지가 → 시가 보정계수 (national single; per-region override below).
    land_price_correction_factor: Decimal = Decimal("1.4")
    land_price_correction_by_region: dict[str, Decimal] = Field(default_factory=dict)

    # §8.3 screening universe (configurable, KOSPI-first default).
    universe: Market = Market.KOSPI

    # --- Land screening thresholds (SPEC-LAND-001) ---
    # Percentile of book/area below which a parcel is flagged "노후 취득 의심".
    land_aged_acquisition_percentile: Decimal = Decimal("0.25")
    # Land book / market-cap ratio above which the land signal is material.
    land_to_marketcap_threshold: Decimal = Decimal("0.30")

    # --- Source behaviour (SPEC-CORE) ---
    cache_dir: Path = Path(".cache")
    cache_ttl_seconds: int = 60 * 60 * 24  # 1 day batch is enough
    max_retries: int = 4
    backoff_base_seconds: float = 1.0
    request_timeout_seconds: float = 30.0
    dart_daily_quota: int = 20_000  # DART OpenAPI documented daily call limit

    def correction_factor_for(self, region: Optional[str]) -> Decimal:
        """Region-specific 보정계수 if configured, else the national factor."""
        if region:
            for key, factor in self.land_price_correction_by_region.items():
                if key and key in region:
                    return factor
        return self.land_price_correction_factor

    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None) -> "Config":
        e = env if env is not None else os.environ

        def _dec(name: str, default: Decimal) -> Decimal:
            raw = e.get(name)
            return Decimal(raw) if raw not in (None, "") else default

        universe_raw = (e.get("ASSET_PLAY_UNIVERSE") or "KOSPI").strip().upper()
        try:
            universe = Market(universe_raw) if universe_raw != "ALL" else Market.UNKNOWN
        except ValueError:
            universe = Market.KOSPI

        return cls(
            dart_api_key=e.get("ASSET_PLAY_DART_API_KEY") or None,
            data_go_kr_key=e.get("ASSET_PLAY_DATA_GO_KR_KEY") or None,
            vworld_key=e.get("ASSET_PLAY_VWORLD_KEY") or None,
            corporate_tax_rate=_dec("ASSET_PLAY_CORPORATE_TAX_RATE", Decimal("0.22")),
            land_price_correction_factor=_dec(
                "ASSET_PLAY_LAND_PRICE_CORRECTION_FACTOR", Decimal("1.4")
            ),
            universe=universe,
            cache_dir=Path(e.get("ASSET_PLAY_CACHE_DIR") or ".cache"),
        )
