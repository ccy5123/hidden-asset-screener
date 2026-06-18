"""SPEC-UNLISTED-001 — AC-1,2."""

from decimal import Decimal

from asset_play.domain.enums import ConfidenceGrade
from asset_play.domain.models import EquityHolding
from asset_play.valuation.unlisted import value_unlisted_holding


def test_ac1_net_asset_approximation_low_confidence():
    holding = EquityHolding(
        investee_name="비상장C", ownership_ratio=Decimal("30"), book_value=Decimal("2000000000")
    )
    v = value_unlisted_holding(holding, net_assets=Decimal("20000000000"))
    # 20,000,000,000 × 30% = 6,000,000,000
    assert v.market_value == Decimal("6000000000")
    assert v.unrealized_gain == Decimal("4000000000")
    assert v.confidence == ConfidenceGrade.LOW
    assert v.unvalued is False


def test_ac2_no_financials_keeps_acquisition_cost_and_flags():
    holding = EquityHolding(
        investee_name="비상장D", ownership_ratio=Decimal("10"), book_value=Decimal("500000000")
    )
    v = value_unlisted_holding(holding, net_assets=None)
    assert v.market_value == Decimal("500000000")  # acquisition cost retained
    assert v.unrealized_gain == Decimal("0")
    assert v.unvalued is True
    assert v.warnings
