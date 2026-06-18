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


def test_from_env_autoloads_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "# comment\nASSET_PLAY_VWORLD_KEY=vw-from-dotenv\nexport ASSET_PLAY_DART_API_KEY='dk'\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ASSET_PLAY_VWORLD_KEY", raising=False)
    monkeypatch.delenv("ASSET_PLAY_DART_API_KEY", raising=False)

    cfg = Config.from_env()
    assert cfg.vworld_key == "vw-from-dotenv"
    assert cfg.dart_api_key == "dk"


def test_real_env_overrides_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ASSET_PLAY_VWORLD_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASSET_PLAY_VWORLD_KEY", "from-real-env")

    cfg = Config.from_env()
    assert cfg.vworld_key == "from-real-env"  # real env wins on conflict


def test_explicit_env_dict_skips_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ASSET_PLAY_VWORLD_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cfg = Config.from_env({})  # explicit dict -> .env must be ignored
    assert cfg.vworld_key is None
