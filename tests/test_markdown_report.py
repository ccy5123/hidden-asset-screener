"""Per-company Markdown report — scenario range + rendering (pure)."""

from decimal import Decimal

from asset_play.report.markdown_report import (
    AssetLine,
    CompanyReport,
    ReportSection,
    render_markdown,
    scenario_navs,
)


def _report():
    eq = AssetLine("상장지분", book=Decimal("100"), est_low=Decimal("90"), est_high=Decimal("150"),
                   confidence="high")
    ip = AssetLine("투자부동산", book=Decimal("300"), est_low=Decimal("700"), est_high=Decimal("700"),
                   confidence="high")
    return CompanyReport(
        name="테스트", stock_code="000000", market_cap=Decimal("400"),
        reported_book_equity=Decimal("500"),
        sections=[ReportSection("자산", [eq, ip])],
        catalyst_score=Decimal("0.40"),
    )


def test_scenario_navs_range():
    scen = scenario_navs(_report())
    navs = sorted(nav for _, nav, _ in scen)
    # 보수 = 자본 500 ; 추정하한 = 500 + (90-100)+(700-300) = 890 ; 추정상한 = 500 + (150-100)+(700-300) = 950
    assert navs[0] == Decimal("500")
    assert Decimal("890") in navs and Decimal("950") in navs
    nds = [nd for *_, nd in scen if nd is not None]
    assert all(nd > 0 for nd in nds)  # 시총 400 < revalued_nav → 양(+)의 할인


def test_scenario_navs_none_without_book_equity():
    rep = _report()
    rep.reported_book_equity = None
    assert scenario_navs(rep) == []


def test_render_markdown_has_sections_and_flags():
    md = render_markdown(_report())
    assert md.startswith("# ")
    for token in ["nav_discount", "상장지분", "투자부동산", "🟢", "catalyst", "각주"]:
        assert token in md
