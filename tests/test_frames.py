"""리포트/스크린/API로그 → DataFrame 순수 빌더 (Streamlit 비의존)."""

from decimal import Decimal

import pandas as pd

from asset_play.report import frames
from asset_play.report.markdown_report import AssetLine, CompanyReport, ReportSection
from asset_play.sources.recorder import ApiCall, RequestRecorder
from asset_play.valuation.screen import ScreenMetrics


def _report() -> CompanyReport:
    eq = AssetLine(label="삼성물산", book=Decimal("100000000"),
                   est_low=Decimal("300000000"), est_high=Decimal("300000000"), confidence="high")
    land = AssetLine(label="타임스퀘어", book=Decimal("331337332000"),
                     est_low=Decimal("331337332000"), est_high=Decimal("745317499000"),
                     confidence="high", note="회사 공시 공정가치")
    return CompanyReport(
        name="경방", stock_code="000050", market_cap=Decimal("200000000000"),
        reported_book_equity=Decimal("900000000000"),
        sections=[ReportSection("상장 보유지분 (종목별)", [eq]),
                  ReportSection("투자부동산·토지 (필지별)", [land])],
        currency="원(₩)", equity_label="별도(OFS) 자본총계", footnotes=["각주1"],
    )


def test_overview_metrics_has_marketcap_and_discount_range():
    m = frames.overview_metrics(_report())
    assert m["시가총액(억)"] == 2000.0
    assert "별도(OFS) 자본총계(억)" in m
    assert m["nav_discount 하한"] is not None and m["nav_discount 상한"] is not None
    assert m["nav_discount 하한"] <= m["nav_discount 상한"]


def test_scenario_frame_three_cases():
    df = frames.scenario_frame(_report())
    assert list(df["시나리오"]) == ["S0 보수 (전 자산=장부)", "S1 추정 하한", "S2 추정 상한"]
    assert set(df.columns) == {"시나리오", "revalued_nav(억)", "nav_discount(%)"}


def test_section_frames_render_range_and_confidence():
    secs = frames.section_frames(_report())
    assert len(secs) == 2
    (_t0, _i0, eq_df) = secs[0]
    assert eq_df.iloc[0]["신뢰"] == "🟢"
    (_t1, _i1, land_df) = secs[1]
    # 차익 상한 = (745,317,499,000 − 331,337,332,000) / 1e8 ≈ 4139.8억
    assert abs(land_df.iloc[0]["차익상한(억)"] - 4139.8) < 0.2
    assert land_df.iloc[0]["비고"] == "회사 공시 공정가치"


def test_screen_value_frame_pass_marks():
    m1 = ScreenMetrics(name="경방", stock_code="000050", market_cap=Decimal("2e11"),
                       equity_controlling=Decimal("1"), equity_total=Decimal("1"),
                       assets_total=Decimal("1"), net_income=Decimal("1"), founded_year=1919,
                       pbr=Decimal("0.29"), equity_ratio=Decimal("0.65"), per=Decimal("8"))
    m2 = ScreenMetrics(name="고PBR", stock_code="000060", market_cap=Decimal("1"),
                       equity_controlling=Decimal("1"), equity_total=Decimal("1"),
                       assets_total=Decimal("1"), net_income=Decimal("1"), founded_year=2010,
                       pbr=Decimal("2.0"), equity_ratio=Decimal("0.3"), per=None)
    df = frames.screen_value_frame([(m1, True), (m2, False)])
    assert list(df["통과"]) == ["✅", "✗"]
    assert df.iloc[0]["자기자본비율(%)"] == 65.0
    assert pd.isna(df.iloc[1]["PER"])   # None → 숫자열에서 NaN


def test_api_calls_frame_marks_cache_and_status():
    rec = RequestRecorder()
    rec.add(ApiCall("DART", "GET", "https://dart/api", {"crtfc_key": "***"}, 200, 12.3, False, "{...}"))
    rec.add(ApiCall("DART", "GET", "https://dart/api2", {}, None, 0.0, True, "{cached}"))
    df = frames.api_calls_frame(rec)
    assert list(df["출처"]) == ["DART", "DART"]
    assert df.iloc[0]["상태"] == "200" and df.iloc[1]["상태"] == "캐시"
