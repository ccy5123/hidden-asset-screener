"""Yahoo Finance 시세 어댑터 (키 불필요) — KR을 해외 IP(Streamlit Cloud)에서도 조회.

KRX(data.krx.co.kr)는 해외 데이터센터 IP를 막아 fdr ``StockListing``이 실패하지만, Yahoo는
글로벌 접근이 된다. ``005930`` → ``005930.KS``(KOSPI)/``.KQ``(KOSDAQ) 로 조회. 비공식
스크레이퍼라 레이트리밋 가능 → 결과는 캐시(1일). yfinance 미설치 시 모든 메서드 None(폴백 위임).

시총 = 종가 × 주식수(Yahoo 보고치). 스크리닝 신호용 근사 — range·신뢰도 전제와 일관.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from ..config import Config
from ..domain.units import to_decimal


class YahooPriceProvider:
    """PriceProvider 구현 — yfinance 경유. 키 불필요. KRX 차단 환경의 KR 시세 폴백/주력."""

    source_name = "Yahoo"

    def __init__(self, config: Optional[Config] = None, *, cache=None) -> None:
        self.config = config or Config()
        self.cache = cache
        self._yf_mod = None
        self._suffix: dict[str, str] = {}  # stock_code → 동작한 접미사(.KS/.KQ) 캐시

    def _yf(self):
        if self._yf_mod is None:
            try:
                import yfinance as yf  # 선택 의존성 — 없으면 None 반환(폴백 위임)
            except ImportError:
                return None
            self._yf_mod = yf
        return self._yf_mod

    def _ticker(self, stock_code: str):
        """동작하는 .KS/.KQ 티커를 찾아 반환(접미사 캐시). 데이터 없으면 None."""
        yf = self._yf()
        if yf is None:
            return None
        order = [self._suffix[stock_code]] if stock_code in self._suffix else [".KS", ".KQ"]
        for sfx in order:
            tk = yf.Ticker(stock_code + sfx)
            try:
                shares = tk.fast_info.get("shares")
            except Exception:
                shares = None
            if shares:
                self._suffix[stock_code] = sfx
                return tk
        return None

    @staticmethod
    def _last_close(tk) -> Optional[Decimal]:
        try:
            hist = tk.history(period="7d")
        except Exception:
            return None
        if hist is None or hist.empty or "Close" not in hist:
            return None
        px = float(hist["Close"].iloc[-1])
        return to_decimal(px) if px and px > 0 else None

    @staticmethod
    def _shares(tk) -> Optional[Decimal]:
        try:
            sh = tk.fast_info.get("shares")
        except Exception:
            sh = None
        return to_decimal(float(sh)) if sh else None

    def get_close_price(self, stock_code: str, on: Optional[date] = None) -> Optional[Decimal]:
        if self.cache is not None:
            hit = self.cache.get_json("yahoo:close", stock_code)
            if hit is not None:
                return to_decimal(hit)
        tk = self._ticker(stock_code)
        px = self._last_close(tk) if tk is not None else None
        if px is not None and self.cache is not None:
            self.cache.set_json("yahoo:close", stock_code, str(px), ttl=self.config.cache_ttl_seconds)
        return px

    def get_shares_outstanding(self, stock_code: str, on: Optional[date] = None) -> Optional[Decimal]:
        if self.cache is not None:
            hit = self.cache.get_json("yahoo:shares", stock_code)
            if hit is not None:
                return to_decimal(hit)
        tk = self._ticker(stock_code)
        sh = self._shares(tk) if tk is not None else None
        if sh is not None and self.cache is not None:
            self.cache.set_json("yahoo:shares", stock_code, str(sh), ttl=self.config.cache_ttl_seconds)
        return sh

    def get_market_cap(self, stock_code: str, on: Optional[date] = None) -> Optional[Decimal]:
        if self.cache is not None:
            hit = self.cache.get_json("yahoo:mktcap", stock_code)
            if hit is not None:
                return to_decimal(hit)
        price = self.get_close_price(stock_code, on)
        shares = self.get_shares_outstanding(stock_code, on)
        mc = price * shares if (price is not None and shares is not None) else None
        if mc is not None and self.cache is not None:
            self.cache.set_json("yahoo:mktcap", stock_code, str(mc), ttl=self.config.cache_ttl_seconds)
        return mc

    def as_of(self, on: Optional[date] = None) -> date:
        return on or date.today()
