"""SPEC-NAV-001 rev.3 AC-5 — realizable vs recognition-only classification."""

from decimal import Decimal

from asset_play.aggregate.nav import SimpleValuation, aggregate_nav
from asset_play.domain.enums import AssetClass, LiquidityClass
from asset_play.domain.models import Company


def test_liquidity_from_purpose():
    assert LiquidityClass.from_purpose("단순투자") == LiquidityClass.REALIZABLE
    assert LiquidityClass.from_purpose("경영참가") == LiquidityClass.RECOGNITION_ONLY
    assert LiquidityClass.from_purpose("경영참여") == LiquidityClass.RECOGNITION_ONLY
    assert LiquidityClass.from_purpose(None) == LiquidityClass.UNKNOWN
    assert LiquidityClass.from_purpose("일반투자") == LiquidityClass.UNKNOWN


def _sv(ac, aid, gain, liq):
    return SimpleValuation(
        asset_class=ac, asset_id=aid,
        book_value=Decimal("10"), market_value=Decimal("10") + gain,
        unrealized_gain=gain, liquidity=liq,
    )


def test_realizable_recognition_subtotals():  # AC-5
    company = Company(corp_code="C", name="X", market_cap=Decimal("400"))
    vals = [
        _sv(AssetClass.INVESTMENT_PROPERTY, "ip", Decimal("200"), LiquidityClass.REALIZABLE),
        _sv(AssetClass.EQUITY, "eq", Decimal("100"), LiquidityClass.RECOGNITION_ONLY),
        _sv(AssetClass.UNLISTED_EQUITY, "u", Decimal("30"), LiquidityClass.UNKNOWN),
    ]
    nav = aggregate_nav(company, vals)
    assert nav.realizable_surplus == Decimal("200")
    assert nav.recognition_only_surplus == Decimal("130")  # 100 + unknown 30 (conservative)
    assert nav.realizable_surplus + nav.recognition_only_surplus == nav.total_unrealized_pretax
    assert any("manual_override" in w for w in nav.warnings)  # unknown flagged


def test_equity_valuation_carries_liquidity_from_purpose():
    from asset_play.domain.models import EquityHolding
    from asset_play.sources.krx import StaticPriceProvider
    from asset_play.valuation.equity import value_equity_holdings

    holdings = [
        EquityHolding(investee_name="단순사", shares=Decimal("10"), book_value=Decimal("100"),
                      investment_purpose="단순투자"),
        EquityHolding(investee_name="경영사", shares=Decimal("10"), book_value=Decimal("100"),
                      investment_purpose="경영참여"),
    ]
    provider = StaticPriceProvider(prices={"000001": Decimal("50"), "000002": Decimal("50")})
    codes = {"단순사": "000001", "경영사": "000002"}
    res = value_equity_holdings(holdings, provider, resolve_stock_code=lambda h: codes[h.investee_name])
    liq = {v.investee_name: v.liquidity for v in res.valuations}
    assert liq["단순사"] == LiquidityClass.REALIZABLE
    assert liq["경영사"] == LiquidityClass.RECOGNITION_ONLY
