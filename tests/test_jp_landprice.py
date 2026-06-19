"""SPEC-JP-002 — 公示地価/地価調査 인덱스 + 영업용 토지 含み益 추정 (pure)."""

from decimal import Decimal

import json

from asset_play.sources.jp_landprice import (
    JpLandPriceIndex,
    LandPricePoint,
    OperatingLandEstimate,
    build_index_from_files,
    category_of,
    estimate_operating_land,
    load_landprice_geojson,
    muni_token,
)


def test_category_of():
    assert category_of("工場") == "industrial"
    assert category_of("倉庫,作業場") == "industrial"
    assert category_of("商業") == "commercial"
    assert category_of("住宅,店舗") == "commercial"   # 店舗 우선(상업)
    assert category_of("住宅") == "residential"
    assert category_of("田") == "other"


def test_muni_token():
    assert muni_token("福岡県筑紫野市") == "筑紫野市"
    assert muni_token("福岡市東区") == "福岡市東区"
    assert muni_token("北海道　札幌市中央区宮の森３条") == "札幌市中央区"
    assert muni_token("京都府京都市下京区") == "京都市下京区"
    assert muni_token("") is None


def _index():
    pts = [
        LandPricePoint("筑紫野市", "住宅", Decimal("110000")),
        LandPricePoint("筑紫野市", "住宅", Decimal("90000")),
        LandPricePoint("筑紫野市", "工場", Decimal("40000")),   # 工業 표준지 존재
        LandPricePoint("福岡市東区", "住宅", Decimal("112000")),  # 工業 표준지 없음 → 할인 폴백
    ]
    return JpLandPriceIndex(pts)


def test_price_per_sqm_uses_matching_use():
    idx = _index()
    # 筑紫野市 industrial → 工場 표준지(40,000) median 직접매칭
    price, conf, matched = idx.price_per_sqm("筑紫野市", "industrial")
    assert price == Decimal("40000") and conf == "med" and matched == "industrial"


def test_price_per_sqm_conservative_discount_fallback():
    idx = _index()
    # 福岡市東区 industrial → 工業 표준지 없음 → 주거 median(112,000)×0.6 = 67,200, 🔴
    price, conf, matched = idx.price_per_sqm("福岡市東区", "industrial")
    assert price == Decimal("67200") and conf == "low" and "주거×0.6" in matched


def test_price_per_sqm_uncovered():
    price, conf, _ = _index().price_per_sqm("札幌市中央区", "residential")
    assert price is None and conf == "low"


def test_estimate_operating_land_industrial_not_overstated():
    idx = _index()
    # 筑紫工場: 工業 표준지 40,000(住宅 110,000 아님) → 과대평가 교정
    est = estimate_operating_land(
        [("福岡県筑紫野市", 101559, 808_000_000, "industrial")], idx
    )[0]
    assert est.price_per_sqm == Decimal("40000")
    assert est.estimate == Decimal("4062360000")       # 101,559 × 40,000
    assert est.gain == Decimal("3254360000")           # − 장부 8.08억엔
    assert est.confidence == "med"


def test_operating_land_estimate_gain_none_when_uncovered():
    e = OperatingLandEstimate("X", Decimal("100"), Decimal("50"), "industrial",
                              None, None, "low", "미커버")
    assert e.gain is None


def test_generic_loader_handles_l01_and_l02_codes(tmp_path):
    # L02 코드(_022/_025/_006) + L01 코드(_006)+내용탐지 주소/用途 둘 다 인식
    gj = {"features": [
        {"properties": {"L02_021": "札幌中央", "L02_022": "北海道　札幌市中央区宮の森",
                        "L02_025": "住宅", "L02_006": 259000}},
        {"properties": {"L01_006": 40000, "addr": "福岡県筑紫野市原田", "use": "工場"}},
    ]}
    p = tmp_path / "x.geojson"
    p.write_text(json.dumps(gj), encoding="utf-8")
    pts = load_landprice_geojson(str(p))
    munis = {pt.muni: pt for pt in pts}
    assert "札幌市中央区" in munis and "筑紫野市" in munis
    assert munis["筑紫野市"].price == Decimal("40000")
    assert category_of(munis["筑紫野市"].use) == "industrial"   # 工場 내용탐지


def test_build_index_from_files_merges(tmp_path):
    g1 = {"features": [{"properties": {"L02_022": "福岡県筑紫野市原田", "L02_025": "住宅", "L02_006": 90000}}]}
    g2 = {"features": [{"properties": {"L01_006": 40000, "addr": "福岡県筑紫野市原田", "use": "工場"}}]}
    p1, p2 = tmp_path / "l02.geojson", tmp_path / "l01.geojson"
    p1.write_text(json.dumps(g1), encoding="utf-8")
    p2.write_text(json.dumps(g2), encoding="utf-8")
    idx = build_index_from_files(str(p1), str(p2))
    # L01 병합 후 筑紫野市에 工業 표준지 생김 → industrial 직접매칭(🟡)
    price, conf, matched = idx.price_per_sqm("筑紫野市", "industrial")
    assert price == Decimal("40000") and conf == "med" and matched == "industrial"
