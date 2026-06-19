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


def _load_dotenv_values(start: Optional[Path] = None) -> dict[str, str]:
    """Parse ``ASSET_PLAY_*`` style ``KEY=VALUE`` pairs from the nearest ``.env``.

    Walks up from ``start`` (default: CWD) until a ``.env`` is found or the
    filesystem root is reached. Returns an empty dict when none exists. Values
    are NOT written to ``os.environ`` — the caller overlays them so that real
    environment variables always win (standard dotenv precedence).
    """
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        env_path = directory / ".env"
        if env_path.is_file():
            break
    else:
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.removeprefix("export ").strip()
        val = val.strip().strip("'").strip('"')
        if key:
            values[key] = val
    return values


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # --- API keys (all free) ---
    dart_api_key: Optional[str] = None
    data_go_kr_key: Optional[str] = None
    vworld_key: Optional[str] = None
    juso_key: Optional[str] = None  # 행안부 도로명주소 검색API (도로명→지번/PNU)
    edinet_key: Optional[str] = None  # EDINET API v2 (JP 有報 XBRL) — Subscription-Key
    jquants_key: Optional[str] = None  # J-Quants V2 (JP 주가) — x-api-key

    # Optional user name-alias DB merged over the packaged default (investee→stock matching).
    name_aliases_path: Optional[Path] = None

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
        # When reading the real environment, auto-load a .env file so keys placed
        # there are picked up without an explicit `export`. Real env vars win on
        # conflict. An explicit `env` dict (tests) skips .env loading entirely.
        if env is None:
            e: dict[str, str] = {**_load_dotenv_values(), **os.environ}
        else:
            e = env

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
            juso_key=e.get("ASSET_PLAY_JUSO_KEY") or None,
            edinet_key=e.get("ASSET_PLAY_EDINET_KEY") or None,
            jquants_key=e.get("ASSET_PLAY_JQUANTS_KEY") or None,
            name_aliases_path=(
                Path(e["ASSET_PLAY_NAME_ALIASES"]) if e.get("ASSET_PLAY_NAME_ALIASES") else None
            ),
            corporate_tax_rate=_dec("ASSET_PLAY_CORPORATE_TAX_RATE", Decimal("0.22")),
            land_price_correction_factor=_dec(
                "ASSET_PLAY_LAND_PRICE_CORRECTION_FACTOR", Decimal("1.4")
            ),
            universe=universe,
            cache_dir=Path(e.get("ASSET_PLAY_CACHE_DIR") or ".cache"),
        )
