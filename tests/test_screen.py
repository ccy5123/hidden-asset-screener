"""자산가치주 1차 스크린 — PBR/자기자본비율/PER 계산 + 필터 (책 1단계)."""

from decimal import Decimal

from asset_play.valuation.screen import (
    ScreenMetrics,
    compute_screen_metrics,
    passes_value_screen,
)


def test_compute_metrics_kyungbang():
    m = compute_screen_metrics(
        name="(주)경방", stock_code="000050",
        market_cap=Decimal("231660000000"),         # 2,316.6억
        equity_controlling=Decimal("759641998841"),  # 지배주주지분 7,596억
        equity_total=Decimal("759626462484"),
        assets_total=Decimal("1214347475924"),
        net_income=Decimal("20000000000"),
        founded_year=1919,
    )
    assert m.pbr == Decimal("0.3050")          # 시총/지배주주지분 ≤ 0.5 ✓
    assert m.equity_ratio == Decimal("0.6255")  # 자본총계/자산총계 ≥ 0.6 ✓
    assert m.founded_year == 1919


def _m(**kw):
    base = dict(name="X", stock_code="0", market_cap=Decimal("100"),
                equity_controlling=Decimal("400"), equity_total=Decimal("400"),
                assets_total=Decimal("600"), net_income=Decimal("12"), founded_year=1980,
                pbr=Decimal("0.25"), equity_ratio=Decimal("0.667"), per=Decimal("8.33"))
    base.update(kw)
    return ScreenMetrics(**base)


def test_passes_value_screen_book_defaults():
    assert passes_value_screen(_m(), pbr_max=Decimal("0.5"), equity_ratio_min=Decimal("0.6"))
    assert passes_value_screen(_m(), pbr_max=Decimal("0.5"), equity_ratio_min=Decimal("0.6"),
                               per_max=Decimal("12"))


def test_passes_filters_reject():
    assert not passes_value_screen(_m(pbr=Decimal("0.8")), pbr_max=Decimal("0.5"))
    assert not passes_value_screen(_m(equity_ratio=Decimal("0.4")), equity_ratio_min=Decimal("0.6"))
    assert not passes_value_screen(_m(per=Decimal("20")), per_max=Decimal("12"))
    assert not passes_value_screen(_m(per=None), per_max=Decimal("12"))  # 적자 → 수익성 탈락
    assert not passes_value_screen(_m(founded_year=2010), founded_before=1990)
    assert passes_value_screen(_m(founded_year=1919), founded_before=1990)
