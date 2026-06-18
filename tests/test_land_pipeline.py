"""Precise land NAV (path B) wired into the pipeline (SPEC-LAND-002).

Pipeline auto-instantiates the V-World geocoder + MOLIT 개별공시지가 source when a
V-World key is configured; parcels supplied via --land-file (location + area, no
fair-value note) are valued at 면적 × 공시지가 × 보정계수.
"""

from datetime import date
from decimal import Decimal

from asset_play.cache import CacheStore
from asset_play.config import Config
from asset_play.domain.enums import AssetClass, Market
from asset_play.domain.models import Company, LandAsset
from asset_play.pipeline import Pipeline
from asset_play.sources.krx import StaticPriceProvider
from asset_play.sources.molit import MolitClient, StaticLandPriceProvider
from asset_play.sources.vworld import StaticGeocoder, VWorldClient

from .fakes import FakeDart


def test_pipeline_auto_wires_land_providers_with_vworld_key():
    keyed = Pipeline(Config(vworld_key="k"), cache=CacheStore())
    assert isinstance(keyed.geocoder, VWorldClient)
    assert isinstance(keyed.land_price_provider, MolitClient)

    none = Pipeline(Config(), cache=CacheStore())
    assert none.geocoder is None
    assert none.land_price_provider is None


def test_precise_land_estimate_flows_into_nav():
    company = Company(corp_code="C", stock_code="000001", name="토지회사", market=Market.KOSPI)
    dart = FakeDart(company, [], stock_to_corp={"000001": "C"})
    # market_cap 1000억: land/marketcap ratio (0.01) is below the shortlist threshold —
    # explicitly-provided parcels must still be valued (human chose them).
    price = StaticPriceProvider(
        market_caps={"000001": Decimal("100000000000")}, as_of_date=date(2026, 6, 1)
    )
    geocoder = StaticGeocoder({"서울 중구 세종대로 110": "1114010300100010000"})
    land = StaticLandPriceProvider({"1114010300100010000": Decimal("2000000")})  # 원/㎡
    pipe = Pipeline(
        Config(), dart=dart, price_provider=price,
        geocoder=geocoder, land_price_provider=land, cache=CacheStore(),
    )
    parcels = {
        "C": [
            LandAsset(
                holder_corp_code="C",
                location_text="서울 중구 세종대로 110",
                area_sqm=Decimal("1000"),
                book_value=Decimal("1000000000"),
            )
        ]
    }
    run = pipe.run(stock_codes=["000001"], land_assets_by_corp=parcels)

    land_agg = run.results[0].by_class[AssetClass.LAND]
    # 1000㎡ × 2,000,000원/㎡ × 1.4(보정계수) = 2,800,000,000 ; gain = 2.8B − 1.0B = 1.8B
    assert land_agg.market_value == Decimal("2800000000")
    assert land_agg.unrealized_gain == Decimal("1800000000")
