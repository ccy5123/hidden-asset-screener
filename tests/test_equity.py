"""SPEC-EQUITY-001 — AC-1..4."""

from datetime import date
from decimal import Decimal

import pytest

from asset_play.domain.enums import FSType
from asset_play.domain.models import EquityHolding
from asset_play.exceptions import InvariantViolation
from asset_play.sources.krx import StaticPriceProvider
from asset_play.valuation.equity import select_separate_fs_holdings, value_equity_holdings


def _provider(**kw):
    kw.setdefault("as_of_date", date(2026, 6, 1))
    kw.setdefault("source_name", "KRX")
    return StaticPriceProvider(**kw)


def test_ac1_precise_unrealized_gain():
    holding = EquityHolding(
        investee_name="상장B",
        investee_stock_code="005930",
        shares=Decimal("1000"),
        book_value=Decimal("10000000"),
        is_investee_listed=True,
    )
    provider = _provider(prices={"005930": Decimal("80000")})
    result = value_equity_holdings([holding], provider)

    assert len(result.valuations) == 1
    v = result.valuations[0]
    # 1000 × 80,000 − 10,000,000 = 70,000,000
    assert v.market_value == Decimal("80000000")
    assert v.unrealized_gain == Decimal("70000000")
    assert v.snapshot.source == "KRX"
    assert v.snapshot.as_of_date == date(2026, 6, 1)


def test_ac2_unlisted_routed_to_tier3():
    holding = EquityHolding(
        investee_name="비상장C", shares=Decimal("100"), book_value=Decimal("500"), is_investee_listed=False
    )
    result = value_equity_holdings([holding], _provider())
    assert result.valuations == []
    assert result.tier3_queue == [holding]


def test_ac3_separate_fs_selected_over_consolidated():
    sep = [EquityHolding(investee_name="A", fs_type=FSType.SEPARATE, book_value=Decimal("1"))]
    con = [EquityHolding(investee_name="A", fs_type=FSType.CONSOLIDATED, book_value=Decimal("2"))]
    assert select_separate_fs_holdings(sep, con) == sep

    with pytest.raises(InvariantViolation):
        select_separate_fs_holdings(None, con)


def test_consolidated_holding_rejected_in_valuation():
    holding = EquityHolding(
        investee_name="A", investee_stock_code="005930", fs_type=FSType.CONSOLIDATED, is_investee_listed=True
    )
    with pytest.raises(InvariantViolation):
        value_equity_holdings([holding], _provider(prices={"005930": Decimal("1")}))


def test_ac4_share_ratio_mismatch_warns_not_stops():
    holding = EquityHolding(
        investee_name="B",
        investee_stock_code="005930",
        shares=Decimal("100"),
        ownership_ratio=Decimal("10"),
        book_value=Decimal("0"),
        is_investee_listed=True,
    )
    provider = _provider(prices={"005930": Decimal("1000")}, market_caps={"005930": Decimal("2000000")})
    result = value_equity_holdings(
        [holding], provider, investee_market_cap=provider.get_market_cap
    )
    v = result.valuations[0]
    assert v.market_value == Decimal("100000")  # shares-based wins
    assert any("불일치" in w for w in v.warnings)


def test_listed_but_unpriced_skipped_with_warning():
    holding = EquityHolding(
        investee_name="B", investee_stock_code="005930", shares=Decimal("100"), is_investee_listed=True
    )
    result = value_equity_holdings([holding], _provider())  # no price for 005930
    assert result.valuations == []
    assert any("unpriced" in w for w in result.warnings)
