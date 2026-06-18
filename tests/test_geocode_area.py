"""도로명→PNU 구성 + 토지특성 면적 자동조회 (SPEC-LAND-002 확장)."""

from decimal import Decimal

from asset_play.domain.models import LandAsset
from asset_play.sources.molit import MolitClient, StaticLandPriceProvider
from asset_play.sources.vworld import CompositeGeocoder, StaticGeocoder, VWorldClient
from asset_play.valuation.land_precise import value_land_precise


def test_construct_pnu_from_reverse_geocode():
    # 법정동코드(10) + 지번(본번-부번) → 19자리 PNU
    assert VWorldClient._construct_pnu("4683033024", "41-2장") == "4683033024100410002"
    assert VWorldClient._construct_pnu("1114010300", "1") == "1114010300100010000"
    assert VWorldClient._construct_pnu("1234567890", "산5-3") == "1234567890200050003"  # 산 → 2
    assert VWorldClient._construct_pnu("1114010300", "") is None


def test_parse_area_from_land_characteristics():
    payload = {
        "landCharacteristicss": {
            "field": [
                {"stdrYear": "2023", "lndpclAr": "1000.0", "pblntfPclnd": "1"},
                {"stdrYear": "2024", "lndpclAr": "1837.6", "pblntfPclnd": "17750000"},
            ]
        }
    }
    assert MolitClient._parse_area(payload) == Decimal("1837.6")  # 최신연도


def test_precise_auto_fetches_area_when_missing():
    geocoder = StaticGeocoder({"서울 중구 태평로1가 1": "1114010300100010000"})
    land = StaticLandPriceProvider(
        prices={"1114010300100010000": Decimal("2000000")},
        areas={"1114010300100010000": Decimal("500")},
    )
    # area 미제공 → provider에서 자동 조회 (500㎡)
    res = value_land_precise(
        [LandAsset(location_text="서울 중구 태평로1가 1", book_value=Decimal("100000000"))],
        geocoder, land,
    )
    assert len(res.valuations) == 1
    # 500㎡ × 2,000,000 × 1.4 = 1,400,000,000
    assert res.valuations[0].market_value == Decimal("1400000000")


def test_composite_geocoder_tries_in_order():
    juso = StaticGeocoder({"평동산단로191": "2920014600109870000"}, match_type="parcel")
    vworld = StaticGeocoder({"광주 북구 임동 136-4": "2917010500101360004"})
    comp = CompositeGeocoder([juso, vworld])
    assert comp.address_to_pnu("평동산단로191") == "2920014600109870000"  # juso
    assert comp.address_to_pnu("광주 북구 임동 136-4") == "2917010500101360004"  # falls to vworld
    assert comp.last_match_type == "parcel"
    assert comp.address_to_pnu("없는주소") is None


def test_road_matched_parcel_routed_to_review_queue():
    # 도로명 자동매칭은 저신뢰 → 자동확정 금지, 검토큐로
    geocoder = StaticGeocoder({"광주 광산구 평동산단로191": "2920014600109880000"}, match_type="road")
    land = StaticLandPriceProvider(
        prices={"2920014600109880000": Decimal("300000")},
        areas={"2920014600109880000": Decimal("9922")},
    )
    res = value_land_precise(
        [LandAsset(location_text="광주 광산구 평동산단로191", book_value=Decimal("23000000000"))],
        geocoder, land,
    )
    assert res.valuations == []  # 자동확정 안 함
    assert len(res.review_queue) == 1
    assert "도로명" in res.review_queue[0].reason
