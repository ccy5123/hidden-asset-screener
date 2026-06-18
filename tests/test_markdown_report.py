"""Per-company Markdown report — scenario range + rendering (pure)."""

from datetime import date
from decimal import Decimal

from asset_play.domain.enums import ConfidenceGrade
from asset_play.domain.models import (
    EquityValuation,
    PreciseLandValuation,
    ReviewQueueItem,
    UnlistedValuation,
    ValuationSnapshot,
)
from asset_play.report.markdown_report import (
    AssetLine,
    CompanyReport,
    ReportSection,
    render_markdown,
    scenario_navs,
    sections_from_valuations,
)


def _snap():
    return ValuationSnapshot(source="test", as_of_date=date(2026, 1, 1))


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


# --------------------------------------------------------------------------- #
# Per-item sections (종목별 / 필지별 / 🔴 검토대기 포함)
# --------------------------------------------------------------------------- #
def test_equity_section_is_per_holding_sorted_by_gain():
    alpha = EquityValuation(asset_id="A", investee_name="알파", book_value=Decimal("100"),
                            market_value=Decimal("300"), unrealized_gain=Decimal("200"),
                            confidence=ConfidenceGrade.HIGH, snapshot=_snap())
    beta = EquityValuation(asset_id="B", investee_name="베타", book_value=Decimal("100"),
                           market_value=Decimal("80"), unrealized_gain=Decimal("-20"),
                           confidence=ConfidenceGrade.HIGH, snapshot=_snap())
    secs = sections_from_valuations([beta, alpha])
    assert len(secs) == 1 and "종목별" in secs[0].title
    # per-holding lines, drivers first (gain_high desc): 알파(+200) before 베타(−20)
    assert [ln.label for ln in secs[0].lines] == ["알파", "베타"]
    assert secs[0].lines[0].confidence == "high"


def test_unlisted_section_separate_from_equity():
    eq = EquityValuation(asset_id="A", investee_name="상장알파", book_value=Decimal("100"),
                         market_value=Decimal("150"), unrealized_gain=Decimal("50"),
                         snapshot=_snap())
    unl = UnlistedValuation(asset_id="U", investee_name="비상장감마", book_value=Decimal("200"),
                            market_value=Decimal("200"), unrealized_gain=Decimal("0"),
                            unvalued=True, snapshot=_snap())
    secs = sections_from_valuations([eq, unl])
    titles = [s.title for s in secs]
    assert any("종목별" in t for t in titles) and any("비상장" in t for t in titles)


def test_land_parcel_range_and_review_queue_included():
    # 필지: 1,000㎡ × 500만원/㎡ = 50억(공시지가) ; 시가보정 ×1.4 = 70억
    land = PreciseLandValuation(
        asset_id="pnu1", location_text="서울 영등포 1", pnu="1" * 19,
        area_sqm=Decimal("1000"), official_price_per_sqm=Decimal("5000000"),
        correction_factor=Decimal("1.4"), book_value=Decimal("1000000000"),
        market_value=Decimal("7000000000"), unrealized_gain=Decimal("6000000000"),
        confidence=ConfidenceGrade.MEDIUM, snapshot=_snap())
    # 검토대기: 도로명 저신뢰 — 무효 처리하지 않고 🔴, 추정값은 상한에만 가산
    rq = ReviewQueueItem(location_text="천안 어딘가", book_value=Decimal("500000000"),
                         reason="도로명 소재지 자동매칭(저신뢰)",
                         raw={"estimated_market_value": "2000000000"})
    secs = sections_from_valuations([land], [rq])
    assert len(secs) == 1 and "필지별" in secs[0].title
    lines = secs[0].lines

    lv = next(ln for ln in lines if "영등포" in ln.label)
    assert lv.est_low == Decimal("5000000000")   # 공시지가×면적
    assert lv.est_high == Decimal("7000000000")  # 시가보정
    assert lv.confidence == "med"

    rv = next(ln for ln in lines if "천안" in ln.label)
    assert rv.confidence == "low"                 # 🔴
    assert rv.est_low == Decimal("500000000")     # 보수=장부 (하한 불변)
    assert rv.est_high == Decimal("2000000000")   # 추정값은 상한에만


def test_review_queue_without_estimate_stays_at_book():
    rq = ReviewQueueItem(location_text="면적불명지", book_value=Decimal("300000000"),
                         reason="면적 불명")
    secs = sections_from_valuations([], [rq])
    ln = secs[0].lines[0]
    assert ln.est_low == ln.est_high == Decimal("300000000")
    assert ln.confidence == "low"


def test_render_per_item_report_shows_labels_and_flags():
    land = PreciseLandValuation(
        asset_id="pnu1", location_text="서울 영등포 1", area_sqm=Decimal("1000"),
        official_price_per_sqm=Decimal("5000000"), correction_factor=Decimal("1.4"),
        book_value=Decimal("1000000000"), market_value=Decimal("7000000000"),
        unrealized_gain=Decimal("6000000000"), confidence=ConfidenceGrade.MEDIUM, snapshot=_snap())
    rq = ReviewQueueItem(location_text="천안 어딘가", book_value=Decimal("500000000"),
                         reason="도로명 저신뢰", raw={"estimated_market_value": "2000000000"})
    rep = CompanyReport(name="테스트", stock_code="000000", market_cap=Decimal("4000000000"),
                        reported_book_equity=Decimal("5000000000"),
                        sections=sections_from_valuations([land], [rq]))
    md = render_markdown(rep)
    assert "영등포" in md and "천안" in md and "🔴" in md and "필지별" in md
