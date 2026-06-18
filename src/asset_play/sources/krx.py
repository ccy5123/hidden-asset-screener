"""KRX market-data adapter (SPEC-CORE-001).

``PriceProvider`` is the seam the rest of the system depends on. ``KrxClient`` is the
live adapter over FinanceDataReader / pykrx (optional extra ``[krx]``); ``StaticPriceProvider``
is the in-memory implementation used by tests and the regression fixtures.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional, Protocol, runtime_checkable

from ..config import Config
from ..domain.units import to_decimal
from ..exceptions import SourceError


@runtime_checkable
class PriceProvider(Protocol):
    source_name: str

    def get_close_price(self, stock_code: str, on: Optional[date] = None) -> Optional[Decimal]: ...

    def get_market_cap(self, stock_code: str, on: Optional[date] = None) -> Optional[Decimal]: ...

    def get_shares_outstanding(
        self, stock_code: str, on: Optional[date] = None
    ) -> Optional[Decimal]: ...

    def as_of(self, on: Optional[date] = None) -> date: ...


class StaticPriceProvider:
    """Deterministic in-memory provider. Prices/market caps are in 원."""

    def __init__(
        self,
        prices: Optional[dict[str, Decimal]] = None,
        market_caps: Optional[dict[str, Decimal]] = None,
        shares: Optional[dict[str, Decimal]] = None,
        as_of_date: Optional[date] = None,
        source_name: str = "static",
    ) -> None:
        self.prices = {k: to_decimal(v) for k, v in (prices or {}).items()}
        self.market_caps = {k: to_decimal(v) for k, v in (market_caps or {}).items()}
        self.shares = {k: to_decimal(v) for k, v in (shares or {}).items()}
        self._as_of = as_of_date or date.today()
        self.source_name = source_name

    def get_close_price(self, stock_code: str, on: Optional[date] = None) -> Optional[Decimal]:
        return self.prices.get(stock_code)

    def get_market_cap(self, stock_code: str, on: Optional[date] = None) -> Optional[Decimal]:
        return self.market_caps.get(stock_code)

    def get_shares_outstanding(
        self, stock_code: str, on: Optional[date] = None
    ) -> Optional[Decimal]:
        return self.shares.get(stock_code)

    def as_of(self, on: Optional[date] = None) -> date:
        return on or self._as_of


class KrxClient:
    """Live adapter over FinanceDataReader / pykrx. Results are cached when a store is given."""

    source_name = "KRX"

    def __init__(self, config: Optional[Config] = None, *, cache=None) -> None:
        self.config = config or Config()
        self.cache = cache
        self._fdr = None
        self._pykrx = None

    def _fdr_mod(self):
        if self._fdr is None:
            try:
                import FinanceDataReader as fdr  # type: ignore
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise SourceError(
                    "FinanceDataReader not installed. `pip install asset-play[krx]` "
                    "or inject a PriceProvider."
                ) from exc
            self._fdr = fdr
        return self._fdr

    def as_of(self, on: Optional[date] = None) -> date:
        return on or date.today()

    def get_close_price(
        self, stock_code: str, on: Optional[date] = None
    ) -> Optional[Decimal]:  # pragma: no cover - requires network/optional dep
        on = on or date.today()
        ckey = f"{stock_code}:{on.isoformat()}"
        if self.cache is not None:
            hit = self.cache.get_json("krx:close", ckey)
            if hit is not None:
                return to_decimal(hit)
        fdr = self._fdr_mod()
        df = fdr.DataReader(stock_code, on.replace(day=1), on)
        if df is None or df.empty:
            return None
        price = to_decimal(float(df["Close"].iloc[-1]))
        if self.cache is not None and price is not None:
            self.cache.set_json("krx:close", ckey, str(price), ttl=self.config.cache_ttl_seconds)
        return price

    def get_market_cap(
        self, stock_code: str, on: Optional[date] = None
    ) -> Optional[Decimal]:  # pragma: no cover - requires network/optional dep
        price = self.get_close_price(stock_code, on)
        shares = self.get_shares_outstanding(stock_code, on)
        if price is None or shares is None:
            return None
        return price * shares

    def get_shares_outstanding(
        self, stock_code: str, on: Optional[date] = None
    ) -> Optional[Decimal]:  # pragma: no cover - requires network/optional dep
        if self.cache is not None:
            hit = self.cache.get_json("krx:shares", stock_code)
            if hit is not None:
                return to_decimal(hit)
        fdr = self._fdr_mod()
        listing = fdr.StockListing("KRX")
        match = listing[listing["Code"] == stock_code]
        if match.empty or "Stocks" not in match:
            return None
        shares = to_decimal(float(match["Stocks"].iloc[0]))
        if self.cache is not None and shares is not None:
            self.cache.set_json("krx:shares", stock_code, str(shares), ttl=self.config.cache_ttl_seconds)
        return shares
