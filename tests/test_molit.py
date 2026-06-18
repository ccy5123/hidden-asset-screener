"""MolitClient 개별공시지가 adapter: key wiring + payload parsing.

The live endpoint is ``api.vworld.kr/ned/...`` (V-World NED), so it authenticates
with the V-World key — not a separate data.go.kr key.
"""

from decimal import Decimal

import pytest

from asset_play.config import Config
from asset_play.exceptions import ConfigError
from asset_play.sources.molit import MolitClient


def test_key_uses_vworld_key():
    # The endpoint is api.vworld.kr/ned/...; it must authenticate with the V-World key.
    cfg = Config(vworld_key="vw-123")
    assert MolitClient(cfg)._key() == "vw-123"


def test_key_missing_raises_configerror():
    with pytest.raises(ConfigError):
        MolitClient(Config())._key()


def test_parse_price_picks_latest_year():
    payload = {
        "indvdLandPrices": {
            "field": [
                {"stdrYear": "2009", "pblntfPclnd": "11000000"},
                {"stdrYear": "2023", "pblntfPclnd": "19200000"},
                {"stdrYear": "2015", "pblntfPclnd": "15000000"},
            ]
        }
    }
    assert MolitClient._parse_price(payload) == Decimal("19200000")
