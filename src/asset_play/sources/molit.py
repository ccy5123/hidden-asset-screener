"""MOLIT land data via 공공데이터포털 (SPEC-LAND-002): 개별공시지가 / 실거래가.

As with KRX, the screener depends on the ``LandPriceProvider`` protocol; ``MolitClient``
is the live adapter and ``StaticLandPriceProvider`` backs tests/the review pipeline.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional, Protocol, runtime_checkable

from ..config import Config
from ..domain.units import to_decimal
from ..exceptions import ConfigError
from .base import HttpSource

MOLIT_LAND_PRICE_URL = (
    "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"  # 개별공시지가 속성 조회
)


@runtime_checkable
class LandPriceProvider(Protocol):
    source_name: str

    def get_official_price_per_sqm(
        self, pnu: str, year: Optional[int] = None
    ) -> Optional[Decimal]: ...

    def as_of(self, year: Optional[int] = None) -> date: ...


class StaticLandPriceProvider:
    """In-memory 개별공시지가 (원/㎡) keyed by PNU."""

    def __init__(
        self,
        prices: Optional[dict[str, Decimal]] = None,
        as_of_year: Optional[int] = None,
        source_name: str = "static-landprice",
    ) -> None:
        self.prices = {k: to_decimal(v) for k, v in (prices or {}).items()}
        self._year = as_of_year or date.today().year
        self.source_name = source_name

    def get_official_price_per_sqm(
        self, pnu: str, year: Optional[int] = None
    ) -> Optional[Decimal]:
        return self.prices.get(pnu)

    def as_of(self, year: Optional[int] = None) -> date:
        return date(year or self._year, 1, 1)


class MolitClient(HttpSource):
    """Live 개별공시지가 adapter (data.go.kr / V-World NED)."""

    source_name = "MOLIT:개별공시지가"

    def _key(self) -> str:
        # 개별공시지가 속성 API is hosted on V-World NED, so a V-World key works (and is
        # preferred). data.go.kr "개별공시지가" is a LINK API that redirects to V-World.
        key = self.config.vworld_key or self.config.data_go_kr_key
        if not key:
            raise ConfigError(
                "land-price API key missing (set ASSET_PLAY_VWORLD_KEY, "
                "or ASSET_PLAY_DATA_GO_KR_KEY)"
            )
        return key

    def as_of(self, year: Optional[int] = None) -> date:
        return date(year or date.today().year, 1, 1)

    @staticmethod
    def _parse_price(payload: dict) -> Optional[Decimal]:
        """Pull 개별공시지가(pblntfPclnd, 원/㎡) from a NED response. Kept separate for tests."""
        fields = payload.get("indvdLandPrices", payload).get("field", []) if isinstance(
            payload.get("indvdLandPrices", payload), dict
        ) else []
        if isinstance(fields, dict):
            fields = [fields]
        latest: Optional[Decimal] = None
        latest_year = -1
        for f in fields:
            price = to_decimal(f.get("pblntfPclnd"))
            year = int(to_decimal(f.get("stdrYear")) or 0)
            if price is not None and year >= latest_year:
                latest, latest_year = price, year
        return latest

    def get_official_price_per_sqm(
        self, pnu: str, year: Optional[int] = None
    ) -> Optional[Decimal]:  # pragma: no cover - requires network/key
        data = self.get_json(
            MOLIT_LAND_PRICE_URL,
            params={
                "key": self._key(),
                "pnu": pnu,
                "format": "json",
                "numOfRows": "50",
                "stdrYear": str(year) if year else "",
            },
            namespace="molit:landprice",
            cache_key=f"{pnu}:{year or 'latest'}",
        )
        return self._parse_price(data)
