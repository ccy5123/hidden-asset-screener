"""SPEC-LAND-002 — AC-1..3 + review-queue invariant (no auto-confirm on failure)."""

from decimal import Decimal

from asset_play.config import Config
from asset_play.domain.models import LandAsset
from asset_play.sources.molit import StaticLandPriceProvider
from asset_play.sources.vworld import StaticGeocoder
from asset_play.valuation.land_precise import value_land_precise


def _config(factor=Decimal("1.4")):
    return Config(land_price_correction_factor=factor)


def test_ac1_precise_valuation_with_confidence():
    land = [LandAsset(location_text="서울시 중구 1-1", area_sqm=Decimal("100"), book_value=Decimal("1000000"))]
    geocoder = StaticGeocoder({"서울시 중구 1-1": "1114010100100010000"})
    prices = StaticLandPriceProvider({"1114010100100010000": Decimal("10000000")})  # 원/㎡
    result = value_land_precise(land, geocoder, prices, config=_config())

    assert len(result.valuations) == 1
    v = result.valuations[0]
    # 100 × 10,000,000 × 1.4 = 1,400,000,000
    assert v.market_value == Decimal("1400000000")
    assert v.unrealized_gain == Decimal("1399000000")
    assert v.confidence is not None
    assert v.snapshot.assumptions["correction_factor"] == "1.4"


def test_ac2_match_failure_goes_to_review_queue_not_confirmed():
    land = [LandAsset(location_text="알수없는주소", area_sqm=Decimal("100"), book_value=Decimal("1"))]
    geocoder = StaticGeocoder({})  # nothing resolves
    result = value_land_precise(land, geocoder, StaticLandPriceProvider({}), config=_config())
    assert result.valuations == []
    assert len(result.review_queue) == 1
    assert "PNU" in result.review_queue[0].reason


def test_ac3_correction_factor_applied_consistently():
    land = [LandAsset(pnu="123", area_sqm=Decimal("10"), book_value=Decimal("0"))]
    prices = StaticLandPriceProvider({"123": Decimal("1000")})
    r14 = value_land_precise(land, StaticGeocoder({}), prices, config=_config(Decimal("1.4")))
    r10 = value_land_precise(land, StaticGeocoder({}), prices, config=_config(Decimal("1.0")))
    assert r14.valuations[0].market_value == Decimal("14000")  # 10×1000×1.4
    assert r10.valuations[0].market_value == Decimal("10000")  # 10×1000×1.0


def test_missing_price_and_missing_area_route_to_review():
    geocoder = StaticGeocoder({"주소A": "PNU_A", "주소B": "PNU_B"})
    land = [
        LandAsset(location_text="주소A", area_sqm=Decimal("100"), book_value=Decimal("1")),  # no price
        LandAsset(location_text="주소B", area_sqm=None, book_value=Decimal("1")),  # no area
    ]
    result = value_land_precise(land, geocoder, StaticLandPriceProvider({}), config=_config())
    assert result.valuations == []
    reasons = {item.reason for item in result.review_queue}
    assert any("공시지가" in r for r in reasons)
    assert any("면적" in r for r in reasons)
