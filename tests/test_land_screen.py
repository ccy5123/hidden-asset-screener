"""SPEC-LAND-001 — AC-1..3."""

from decimal import Decimal

from asset_play.domain.enums import MeasurementModel
from asset_play.domain.models import Company, LandAsset
from asset_play.valuation.land_screen import screen_land


def _company(model=MeasurementModel.COST, market_cap=Decimal("1000000000")):
    return Company(
        corp_code="00000001",
        stock_code="000001",
        name="테스트",
        market_cap=market_cap,
        land_measurement_model=model,
    )


def test_ac1_revaluation_model_excluded():
    company = _company(model=MeasurementModel.REVALUATION)
    land = [LandAsset(book_value=Decimal("500000000"), area_sqm=Decimal("1000"))]
    result = screen_land(company, land)
    assert result.excluded is True
    assert result.shortlisted is False
    assert "재평가" in result.exclude_reason


def test_ac2_investment_property_fair_value_used():
    company = _company()
    land = [
        LandAsset(book_value=Decimal("100000000"), fair_value=Decimal("400000000"), area_sqm=Decimal("500"))
    ]
    result = screen_land(company, land)
    assert result.investment_property_fair_value == Decimal("400000000")
    assert result.investment_property_gain == Decimal("300000000")
    assert any("투자부동산" in f for f in result.flags)
    assert result.snapshot is not None
    assert result.shortlisted is True


def test_ac3_low_book_per_sqm_flagged_aged():
    company = _company(market_cap=Decimal("100000000000"))  # large cap → ratio signal off
    # subject: 1,000,000원 / 1000㎡ = 1,000 원/㎡ (very low)
    land = [LandAsset(book_value=Decimal("1000000"), area_sqm=Decimal("1000"))]
    peers = [Decimal("50000"), Decimal("80000"), Decimal("120000"), Decimal("200000")]
    result = screen_land(company, land, peer_book_per_sqm=peers)
    assert result.book_per_sqm == Decimal("1000.00")
    assert any("노후 취득 의심" in f for f in result.flags)
    assert result.shortlisted is True


def test_high_land_to_marketcap_shortlists():
    company = _company(market_cap=Decimal("1000000000"))
    land = [LandAsset(book_value=Decimal("800000000"), area_sqm=Decimal("10000"))]
    result = screen_land(company, land)
    assert result.land_to_marketcap_ratio == Decimal("0.8000")
    assert result.shortlisted is True
    assert result.signal_score > 0
