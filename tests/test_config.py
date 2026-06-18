"""Config loading + region-specific correction factor."""

from decimal import Decimal

from asset_play.config import Config
from asset_play.domain.enums import Market


def test_from_env_defaults_and_overrides():
    cfg = Config.from_env({})
    assert cfg.corporate_tax_rate == Decimal("0.22")
    assert cfg.land_price_correction_factor == Decimal("1.4")
    assert cfg.universe == Market.KOSPI

    cfg2 = Config.from_env(
        {
            "ASSET_PLAY_DART_API_KEY": "k",
            "ASSET_PLAY_CORPORATE_TAX_RATE": "0.264",
            "ASSET_PLAY_UNIVERSE": "KOSDAQ",
        }
    )
    assert cfg2.dart_api_key == "k"
    assert cfg2.corporate_tax_rate == Decimal("0.264")
    assert cfg2.universe == Market.KOSDAQ


def test_correction_factor_region_override():
    cfg = Config(land_price_correction_by_region={"서울": Decimal("1.6")})
    assert cfg.correction_factor_for("서울특별시 중구") == Decimal("1.6")
    assert cfg.correction_factor_for("부산광역시") == Decimal("1.4")  # falls back to national
    assert cfg.correction_factor_for(None) == Decimal("1.4")
