"""Land sources: V-World key fallback, 개별공시지가 parse, PNU parse, static providers."""

from decimal import Decimal

import pytest

from asset_play.config import Config
from asset_play.exceptions import ConfigError
from asset_play.sources.molit import MolitClient, StaticLandPriceProvider
from asset_play.sources.vworld import StaticGeocoder, VWorldClient


def test_molit_key_prefers_vworld_then_data_go_kr():
    assert MolitClient(Config(vworld_key="vw"))._key() == "vw"
    assert MolitClient(Config(data_go_kr_key="dg"))._key() == "dg"
    assert MolitClient(Config(vworld_key="vw", data_go_kr_key="dg"))._key() == "vw"
    with pytest.raises(ConfigError):
        MolitClient(Config())._key()


def test_molit_parse_price_picks_latest_year():
    payload = {
        "indvdLandPrices": {
            "field": [
                {"pnu": "1", "stdrYear": "2023", "pblntfPclnd": "1000000"},
                {"pnu": "1", "stdrYear": "2024", "pblntfPclnd": "1200000"},
            ]
        }
    }
    assert MolitClient._parse_price(payload) == Decimal("1200000")


def test_vworld_parse_pnu_ok_and_fail():
    # 실측: getcoord 응답의 19자리 PNU는 refined.structure.level4LC 에 있다 (result는 x/y 좌표).
    ok = {"response": {"status": "OK",
                       "refined": {"structure": {"level4LC": "1234567890123456789"}}}}
    assert VWorldClient._parse_pnu(ok) == "1234567890123456789"
    assert VWorldClient._parse_pnu({"response": {"status": "NOT_FOUND"}}) is None
    assert VWorldClient._parse_pnu({}) is None


def test_static_providers():
    lp = StaticLandPriceProvider({"P": Decimal("100")})
    assert lp.get_official_price_per_sqm("P") == Decimal("100")
    assert lp.get_official_price_per_sqm("X") is None

    g = StaticGeocoder({"addr": "PNU"})
    assert g.address_to_pnu("addr") == "PNU"
    assert g.address_to_pnu("unknown") is None
