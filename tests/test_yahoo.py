"""Yahoo 시세 제공자 + CompositePriceProvider 폴백 + price_source 라우팅 (네트워크 없음)."""

from datetime import date
from decimal import Decimal

import pandas as pd

from asset_play.config import Config
from asset_play.domain.units import to_decimal
from asset_play.market import _kr_price_provider
from asset_play.sources.krx import CompositePriceProvider, KrxClient
from asset_play.sources.yahoo import YahooPriceProvider


# -- 가짜 yfinance ------------------------------------------------------------ #
class _FastInfo:
    def __init__(self, shares):
        self._d = {"shares": shares}

    def get(self, k):
        return self._d.get(k)


class _Tk:
    def __init__(self, shares, close):
        self._shares = shares
        self._close = close

    @property
    def fast_info(self):
        return _FastInfo(self._shares)

    def history(self, period="7d"):
        if self._close is None:
            return pd.DataFrame()
        return pd.DataFrame({"Close": [self._close]})


class _FakeYF:
    def __init__(self, by_ticker):
        self.by_ticker = by_ticker

    def Ticker(self, code):
        return self.by_ticker.get(code, _Tk(None, None))


def _yahoo(by_ticker):
    p = YahooPriceProvider(Config())
    p._yf_mod = _FakeYF(by_ticker)  # 실제 yfinance import 우회(네트워크 없음)
    return p


def test_yahoo_market_cap_is_close_times_shares():
    p = _yahoo({"000050.KS": _Tk(25986851, 8020.0)})
    assert p.get_close_price("000050") == to_decimal(8020.0)
    assert p.get_shares_outstanding("000050") == to_decimal(25986851)
    assert p.get_market_cap("000050") == to_decimal(8020.0) * to_decimal(25986851)


def test_yahoo_falls_back_to_kosdaq_suffix():
    # .KS는 데이터 없음(shares None) → .KQ로
    p = _yahoo({"035420.KS": _Tk(None, None), "035420.KQ": _Tk(1000, 50.0)})
    assert p.get_market_cap("035420") == to_decimal(50.0) * to_decimal(1000)


def test_yahoo_none_when_no_data():
    p = _yahoo({})  # 어떤 티커도 데이터 없음
    assert p.get_market_cap("999999") is None
    assert p.get_close_price("999999") is None


def test_yahoo_none_when_yfinance_missing(monkeypatch):
    p = YahooPriceProvider(Config())
    monkeypatch.setattr(p, "_yf", lambda: None)  # yfinance 미설치 시뮬
    assert p.get_market_cap("000050") is None


# -- CompositePriceProvider 폴백 --------------------------------------------- #
class _P:
    def __init__(self, mc=None, raise_=False):
        self.mc = mc
        self.raise_ = raise_

    def _v(self):
        if self.raise_:
            raise RuntimeError("boom")
        return self.mc

    def get_market_cap(self, sc, on=None):
        return self._v()

    def get_close_price(self, sc, on=None):
        return self._v()

    def get_shares_outstanding(self, sc, on=None):
        return self._v()

    def as_of(self, on=None):
        return date(2026, 1, 1)


def test_composite_returns_first_non_none():
    c = CompositePriceProvider([_P(mc=None), _P(mc=Decimal("100"))])
    assert c.get_market_cap("x") == Decimal("100")


def test_composite_skips_raising_provider():
    c = CompositePriceProvider([_P(raise_=True), _P(mc=Decimal("50"))])
    assert c.get_market_cap("x") == Decimal("50")


def test_composite_all_none():
    assert CompositePriceProvider([_P(), _P()]).get_market_cap("x") is None


# -- price_source 라우팅 / config -------------------------------------------- #
def test_kr_price_provider_routing():
    assert isinstance(_kr_price_provider(Config(price_source="krx"), None), KrxClient)
    assert isinstance(_kr_price_provider(Config(price_source="yahoo"), None), YahooPriceProvider)
    auto = _kr_price_provider(Config(price_source="auto"), None)
    assert isinstance(auto, CompositePriceProvider)
    assert [type(p).__name__ for p in auto.providers] == ["YahooPriceProvider", "KrxClient"]


def test_config_price_source_from_env():
    assert Config.from_env({"ASSET_PLAY_PRICE_SOURCE": "YAHOO"}).price_source == "yahoo"
    assert Config.from_env({}).price_source == "auto"
