"""멀티마켓 CLI 라우팅 — 종목코드 자리수(JP 4 / KR 6)로 시장 자동판별 + 어댑터 주입.

KR `asset-play report --stock 000050` 와 JP `asset-play report --stock 9031` 가 같은 CLI로
구동되고, 자리수만으로 올바른 어댑터(Kr/Jp)가 선택되는지 검증한다.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from asset_play import __main__ as cli
from asset_play.config import Config
from asset_play.sources.adapter import JpAdapter, KrAdapter
from asset_play.sources.jp_landprice import JpLandPriceIndex


# -- Config: ASSET_PLAY_LANDPRICE_FILES 파싱 (콤마/경로구분자) ----------------- #
def test_config_parses_landprice_files_comma():
    cfg = Config.from_env({"ASSET_PLAY_LANDPRICE_FILES": "L01.geojson, L02.geojson"})
    assert [p.name for p in cfg.landprice_files] == ["L01.geojson", "L02.geojson"]


def test_config_landprice_files_empty_by_default():
    assert Config.from_env({}).landprice_files == []


# -- detect_market: 자리수 기반 + override ------------------------------------ #
def test_detect_market_by_digit_length():
    assert cli.detect_market("9031") == "jp"        # JP 티커 4자리
    assert cli.detect_market("000050") == "kr"      # KR 종목 6자리
    assert cli.detect_market("00101628") == "kr"    # KR corp_code 8자리


def test_detect_market_override_wins():
    assert cli.detect_market("000050", "jp") == "jp"
    assert cli.detect_market("9031", "kr") == "kr"


def test_detect_market_rejects_unknown_override():
    with pytest.raises(ValueError):
        cli.detect_market("9031", "us")


# -- resolve_market: 동질성 검사 --------------------------------------------- #
def test_resolve_market_homogeneous():
    assert cli.resolve_market(["9031"], None) == "jp"
    assert cli.resolve_market(["000050", "000950"], None) == "kr"


def test_resolve_market_empty_defaults_kr():
    assert cli.resolve_market([], None) == "kr"


def test_resolve_market_mixed_rejected():
    with pytest.raises(ValueError):
        cli.resolve_market(["9031", "000050"], None)


def test_resolve_market_override_skips_mix_check():
    # override가 있으면 코드 자리수 혼합이어도 강제 시장 사용
    assert cli.resolve_market(["9031", "000050"], "jp") == "jp"


# -- make_pipeline: 어댑터 주입 (네트워크 없음) ------------------------------- #
def test_make_pipeline_kr_uses_kr_adapter(tmp_path):
    cfg = Config(cache_dir=tmp_path)
    pipe = cli.make_pipeline(cfg, "kr")
    assert isinstance(pipe.adapter, KrAdapter)


def test_make_pipeline_jp_uses_jp_adapter_no_landprice(tmp_path):
    cfg = Config(cache_dir=tmp_path)
    pipe = cli.make_pipeline(cfg, "jp")
    assert isinstance(pipe.adapter, JpAdapter)
    assert pipe.adapter.landprice_index is None       # 파일 없음 → 영업용 토지 추정 생략


def test_make_pipeline_jp_builds_landprice_index(tmp_path):
    gj = {"features": [
        {"properties": {"L02_022": "福岡県筑紫野市原田", "L02_025": "工場", "L02_006": 40000}},
    ]}
    geo = tmp_path / "l02.geojson"
    geo.write_text(json.dumps(gj), encoding="utf-8")
    cfg = Config(cache_dir=tmp_path)
    pipe = cli.make_pipeline(cfg, "jp", extra_landprice=[str(geo)])
    assert isinstance(pipe.adapter, JpAdapter)
    assert isinstance(pipe.adapter.landprice_index, JpLandPriceIndex)


def test_make_pipeline_jp_merges_config_landprice_files(tmp_path):
    gj = {"features": [
        {"properties": {"L01_006": 50000, "addr": "福岡県筑紫野市原田", "use": "工場"}},
    ]}
    geo = tmp_path / "l01.geojson"
    geo.write_text(json.dumps(gj), encoding="utf-8")
    cfg = Config(cache_dir=tmp_path, landprice_files=[geo])  # 환경변수/config 경유
    pipe = cli.make_pipeline(cfg, "jp")
    assert isinstance(pipe.adapter.landprice_index, JpLandPriceIndex)


# -- CLI report: 자리수로 시장 라우팅 (build/write/pipeline 가짜) ------------- #
def _spy_report(monkeypatch):
    """report 커맨드 배선을 가짜로 — _make_pipeline 호출 시장을 캡처."""
    captured: dict = {}

    def _fake_make(config, market, *, extra_landprice=None):
        captured["market"] = market
        captured["extra_landprice"] = extra_landprice
        return SimpleNamespace(adapter=SimpleNamespace(corp_code_for_stock=lambda c: None))

    def _fake_build(*_, **__):
        return SimpleNamespace(name="X", stock_code="X")

    def _fake_write(report, path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        return p

    monkeypatch.setattr(cli, "make_pipeline", _fake_make)
    monkeypatch.setattr("asset_play.report.markdown_report.build_company_report", _fake_build)
    monkeypatch.setattr("asset_play.report.markdown_report.write_markdown", _fake_write)
    return captured


def test_report_routes_jp_for_4digit(tmp_path, monkeypatch):
    captured = _spy_report(monkeypatch)
    rc = cli.main(["report", "--stock", "9031", "--out", str(tmp_path)])
    assert rc == 0 and captured["market"] == "jp"


def test_report_routes_kr_for_6digit(tmp_path, monkeypatch):
    captured = _spy_report(monkeypatch)
    rc = cli.main(["report", "--stock", "000050", "--out", str(tmp_path)])
    assert rc == 0 and captured["market"] == "kr"


def test_report_market_override(tmp_path, monkeypatch):
    captured = _spy_report(monkeypatch)
    rc = cli.main(["report", "--stock", "000050", "--market", "jp", "--out", str(tmp_path)])
    assert rc == 0 and captured["market"] == "jp"


def test_report_landprice_file_forwarded(tmp_path, monkeypatch):
    captured = _spy_report(monkeypatch)
    rc = cli.main(["report", "--stock", "9031", "--landprice-file", "a.geojson",
                   "--landprice-file", "b.geojson", "--out", str(tmp_path)])
    assert rc == 0 and captured["extra_landprice"] == ["a.geojson", "b.geojson"]
