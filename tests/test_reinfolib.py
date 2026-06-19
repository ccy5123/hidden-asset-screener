"""reinfolib XPT002 地価 API 클라이언트 + reinfolib판 영업용 토지 추정 (네트워크 없음)."""

from decimal import Decimal

from asset_play.config import Config
from asset_play.sources.jp_landprice import LandPricePoint, estimate_operating_land_reinfolib
from asset_play.sources.reinfolib import ReinfolibClient, _muni, _price, _tile


def test_tile_tokyo_station():
    assert _tile(35.6812, 139.7671, 13) == (7276, 3225)


def test_price_parses_current_then_falls_back():
    assert _price({"u_current_years_price_ja": "36,800,000(円/㎡)"}) == Decimal("36800000")
    assert _price({"last_years_price": 3110000}) == Decimal("3110000")   # 폴백(작년 정수)
    assert _price({}) is None


def test_muni_combines_city_and_ward():
    assert _muni({"city_county_name_ja": "福岡市", "ward_town_village_name_ja": "東区"}) == "福岡市東区"
    assert _muni({"city_county_name_ja": "", "ward_town_village_name_ja": "千代田区"}) == "千代田区"
    assert _muni({}) is None


def test_land_points_parses_geojson(monkeypatch):
    gj = {"features": [{
        "geometry": {"type": "Point", "coordinates": [139.7639, 35.6811]},
        "properties": {"u_current_years_price_ja": "36,800,000(円/㎡)",
                       "use_category_name_ja": "商業地",
                       "city_county_name_ja": "", "ward_town_village_name_ja": "千代田区"},
    }]}

    class _R:
        status_code = 200
        text = "ok"

        def json(self):
            return gj

    monkeypatch.setattr("requests.get", lambda *a, **k: _R())
    c = ReinfolibClient(Config(reinfolib_key="k"))
    pts = c.land_points(35.681, 139.764, year=2024)
    assert len(pts) == 1
    p = pts[0]
    assert p.muni == "千代田区" and p.use == "商業地" and p.price == Decimal("36800000")
    assert abs(p.lat - 35.6811) < 1e-6 and abs(p.lon - 139.7639) < 1e-6


def test_land_points_empty_on_http_error(monkeypatch):
    class _R:
        status_code = 403
        text = "forbidden"

        def json(self):
            return {}

    monkeypatch.setattr("requests.get", lambda *a, **k: _R())
    assert ReinfolibClient(Config(reinfolib_key="k")).land_points(35.0, 139.0, year=2024) == []


def test_default_year_is_previous_when_unset():
    from datetime import date
    assert ReinfolibClient(Config()).default_year() == date.today().year - 1
    assert ReinfolibClient(Config(reinfolib_year=2025)).default_year() == 2025


# -- reinfolib판 영업용 토지 추정 ------------------------------------------- #
class _FakeClient:
    def __init__(self, points):
        self.points = points

    def land_points(self, lat, lon, year=None):
        return self.points


class _Geo:
    def geocode(self, addr):
        return (33.5, 130.4)


def test_estimate_reinfolib_uses_nearest_point():
    pts = [LandPricePoint("福岡市東区", "工業地", Decimal("159000"), lat=33.5, lon=130.4)]
    est = estimate_operating_land_reinfolib(
        [("福岡県福岡市東区...", 1000, 10_000_000, "industrial")], _FakeClient(pts), _Geo())[0]
    assert est.price_per_sqm == Decimal("159000")
    assert est.estimate == Decimal("159000") * Decimal("1000")
    assert est.gain == Decimal("159000000") - Decimal("10000000")
    assert "reinfolib" in est.matched


def test_estimate_reinfolib_low_without_geocoder():
    est = estimate_operating_land_reinfolib(
        [("어딘가", 1000, 1_000_000, "industrial")], _FakeClient([]), None)[0]
    assert est.price_per_sqm is None and est.confidence == "low"
