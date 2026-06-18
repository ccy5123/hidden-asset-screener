"""Per-company Markdown 점검 보고서 — 자산유형별 케이스 range + 신뢰도(🟢🟡🔴) + 각주.

단일 점추정이 틀릴 수 있으므로(예: 도로명 오매칭, 부분소유), 각 자산을 **[보수=장부 ~ 추정시가]
range** 로 잡고, 신뢰도를 색으로 표기한다. 종합 nav_discount도 시나리오 range로 보여준다.

순수 렌더(render_markdown)와 range 로직(scenario_navs)은 입력 데이터만 의존(테스트 가능).
build_company_report 가 파이프라인 결과(NAVResult)로 데이터를 조립한다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Union

from ..domain.enums import AssetClass, ConfidenceGrade

_CONF = {"high": "🟢", "med": "🟡", "low": "🔴"}

# ConfidenceGrade(高/中/低) → 표시 신뢰도
_GRADE_CONF = {
    ConfidenceGrade.HIGH: "high",
    ConfidenceGrade.MEDIUM: "med",
    ConfidenceGrade.LOW: "low",
}


@dataclass
class AssetLine:
    """한 자산(군). 가치는 [est_low, est_high] range, 장부가 대비 차익으로 환산."""

    label: str
    book: Decimal
    est_low: Decimal
    est_high: Decimal
    confidence: str = "med"  # high|med|low
    note: Optional[str] = None

    @property
    def gain_low(self) -> Decimal:
        return self.est_low - self.book

    @property
    def gain_high(self) -> Decimal:
        return self.est_high - self.book


@dataclass
class ReportSection:
    title: str
    lines: list  # list[AssetLine]
    intro: Optional[str] = None


@dataclass
class CompanyReport:
    name: str
    stock_code: str
    market_cap: Optional[Decimal]
    reported_book_equity: Optional[Decimal]  # 별도(OFS) 자본총계
    sections: list = field(default_factory=list)  # list[ReportSection]
    catalyst_score: Optional[Decimal] = None
    value_trap: bool = False
    source: str = ""
    asof: Optional[date] = None
    footnotes: list = field(default_factory=list)  # list[str]


def _lines(report: CompanyReport) -> list:
    return [ln for s in report.sections for ln in s.lines]


def scenario_navs(report: CompanyReport) -> list:
    """[(시나리오, revalued_nav, nav_discount)] — 보수(장부)/추정하한/추정상한."""
    be = report.reported_book_equity
    if be is None:
        return []
    gain_lo = sum((ln.gain_low for ln in _lines(report)), Decimal(0))
    gain_hi = sum((ln.gain_high for ln in _lines(report)), Decimal(0))
    scen = [
        ("S0 보수 (전 자산=장부)", be),
        ("S1 추정 하한", be + gain_lo),
        ("S2 추정 상한", be + gain_hi),
    ]
    mc = report.market_cap
    out = []
    for name, nav in scen:
        nd = None
        if mc and mc > 0 and nav > 0:
            nd = (Decimal(1) - mc / nav).quantize(Decimal("0.0001"))
        out.append((name, nav, nd))
    return out


def _eok(x: Optional[Decimal]) -> str:
    return "—" if x is None else f"{float(x) / 1e8:,.1f}억"


def _pct(x: Optional[Decimal]) -> str:
    return "—" if x is None else f"{float(x) * 100:.1f}%"


def render_markdown(report: CompanyReport) -> str:
    o: list = []
    o.append(f"# 자산가치 점검 — {report.name} ({report.stock_code})\n")
    meta = []
    if report.source:
        meta.append(f"출처 {report.source}")
    if report.asof:
        meta.append(f"시세 기준 {report.asof.isoformat()}")
    if meta:
        o.append("> " + " · ".join(meta))
    o.append("> ⚠️ 각 자산은 **[보수=장부 ~ 추정시가] range**. 신뢰도 🟢 관측/공시 · 🟡 추정 · 🔴 신뢰↓.\n")

    scen = scenario_navs(report)
    o.append("## 1. 종합 — 케이스별 range\n")
    o.append(f"- 시총 **{_eok(report.market_cap)}** · 별도(OFS) 자본총계 **{_eok(report.reported_book_equity)}**")
    if scen:
        nds = [nd for *_, nd in scen if nd is not None]
        if nds:
            o.append(f"- **nav_discount 범위: {_pct(min(nds))} ~ {_pct(max(nds))}**\n")
        o.append("| 시나리오 | revalued_nav | nav_discount |")
        o.append("|---|---|---|")
        for name, nav, nd in scen:
            o.append(f"| {name} | {_eok(nav)} | {_pct(nd)} |")
        o.append("")
    else:
        o.append("- (별도 자본총계 없음 → revalued_nav/nav_discount 산출 불가)\n")

    n = 2
    for s in report.sections:
        o.append(f"## {n}. {s.title}\n")
        if s.intro:
            o.append(f"> {s.intro}\n")
        o.append("| 자산 | 장부가 | 추정시가 (하한~상한) | 차익 (하한~상한) | 신뢰 |")
        o.append("|---|---|---|---|---|")
        for ln in s.lines:
            rng = _eok(ln.est_low) if ln.est_low == ln.est_high else f"{_eok(ln.est_low)} ~ {_eok(ln.est_high)}"
            grg = _eok(ln.gain_low) if ln.gain_low == ln.gain_high else f"{_eok(ln.gain_low)} ~ {_eok(ln.gain_high)}"
            o.append(f"| {ln.label} | {_eok(ln.book)} | {rng} | {grg} | {_CONF.get(ln.confidence, '🟡')} |")
        o.append("")
        # 주석: 동일 문구는 한 번만(비상장 다수 항목 중복 방지). 한 항목에만 붙는 고유 주석은 라벨과 함께.
        counts = Counter(ln.note for ln in s.lines if ln.note)
        shown: set = set()
        for ln in s.lines:
            if not ln.note or ln.note in shown:
                continue
            shown.add(ln.note)
            conf = _CONF.get(ln.confidence, "🟡")
            if counts[ln.note] > 1:
                o.append(f"- {conf} {ln.note}")  # 공통 주석 (여러 항목 공유)
            else:
                o.append(f"- {conf} **{ln.label}**: {ln.note}")  # 고유 주석
        o.append("")
        n += 1

    if report.catalyst_score is not None:
        o.append(f"## {n}. 카탈리스트\n")
        o.append("> 숨은가치가 *풀릴지*는 카탈리스트(밸류업·자사주·배당)에 달림.\n")
        trap = " · ⚠️ **value trap 경계**" if report.value_trap else ""
        o.append(f"- **catalyst_score = {report.catalyst_score}**{trap}\n")
        n += 1

    o.append(f"## {n}. 각주\n")
    for f in report.footnotes:
        o.append(f"- {f}")
    return "\n".join(o) + "\n"


def write_markdown(report: CompanyReport, path: Union[str, Path]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Per-item AssetLine builders — 종목별/필지별 detail (NAVResult.by_class only has rollups)
# --------------------------------------------------------------------------- #
def _grade(v) -> str:
    return _GRADE_CONF.get(getattr(v, "confidence", None), "med")


def _equity_line(v) -> AssetLine:
    """상장 보유지분: 2시점 [장부 계상액 → 현재 시가]. 시가는 단일가(점)."""
    return AssetLine(
        label=getattr(v, "investee_name", None) or v.asset_id,
        book=v.book_value, est_low=v.market_value, est_high=v.market_value,
        confidence=_grade(v) or "high",
    )


def _unlisted_line(v) -> AssetLine:
    note = "순자산×지분율 근사 — 시장가 아님"
    if getattr(v, "unvalued", False):
        note += " (미평가: 장부=시가)"
    return AssetLine(
        label=getattr(v, "investee_name", None) or v.asset_id,
        book=v.book_value, est_low=v.market_value, est_high=v.market_value,
        confidence="med", note=note,
    )


def _ip_line(v) -> AssetLine:
    return AssetLine(
        label="투자부동산(공정가치 주석)", book=v.book_value,
        est_low=v.market_value, est_high=v.market_value, confidence="high",
        note="회사 공시 공정가치 — 영업용 토지보다 신뢰 높음.",
    )


def _land_line(v) -> AssetLine:
    """영업용/투자 토지 필지: range [공시지가×면적 ~ 시가보정]. S0 보수는 취득원가(book)."""
    price = getattr(v, "official_price_per_sqm", None)
    area = getattr(v, "area_sqm", None)
    mv = v.market_value
    base = (area * price).quantize(Decimal(1)) if price and area else mv  # 공시지가×면적 (보정 ×1.0)
    est_low, est_high = (base, mv) if base <= mv else (mv, base)
    loc = getattr(v, "location_text", None) or getattr(v, "pnu", None) or v.asset_id
    bits = []
    if area and price:
        c = getattr(v, "correction_factor", Decimal(1))
        bits.append(f"{float(area):,.0f}㎡ × {float(price):,.0f}원/㎡ · 보정 ×{c}")
    if getattr(v, "pnu", None):
        bits.append(f"PNU {v.pnu}")
    return AssetLine(label=loc, book=v.book_value, est_low=est_low, est_high=est_high,
                     confidence=_grade(v), note=" · ".join(bits) or None)


def _review_line(r) -> AssetLine:
    """검토대기 필지(매칭 저신뢰): 무효 처리하지 않고 🔴로 표시 — 추정값이 있으면 range 상한에만 가산."""
    book = r.book_value
    est = None
    raw = getattr(r, "raw", None) or {}
    if raw.get("estimated_market_value"):
        try:
            est = Decimal(raw["estimated_market_value"])
        except (ValueError, ArithmeticError):
            est = None
    return AssetLine(
        label=(getattr(r, "location_text", None) or "필지(소재지 불명)"),
        book=book, est_low=book, est_high=(est if est is not None else book),
        confidence="low", note=f"검토대기: {r.reason}",
    )


def sections_from_valuations(valuations, review_queue=None) -> list:
    """per-item 평가 + 검토대기 → 보고서 섹션(상장지분 종목별 / 비상장 / 투자부동산·토지 필지별).

    순수 함수(입력만 의존) — 평가 모델 리스트만 받아 ReportSection 리스트를 만든다.
    """
    eq, unl, land = [], [], []
    for v in valuations or []:
        ac = getattr(v, "asset_class", None)
        if ac == AssetClass.EQUITY:
            eq.append(_equity_line(v))
        elif ac == AssetClass.UNLISTED_EQUITY:
            unl.append(_unlisted_line(v))
        elif ac == AssetClass.INVESTMENT_PROPERTY:
            land.append(_ip_line(v))
        elif ac == AssetClass.LAND:
            land.append(_land_line(v))
        else:
            unl.append(AssetLine(label=str(ac), book=v.book_value,
                                 est_low=v.market_value, est_high=v.market_value, confidence="med"))
    for r in review_queue or []:
        land.append(_review_line(r))  # 🔴 포함 (제외 금지)

    eq.sort(key=lambda ln: ln.gain_high, reverse=True)
    unl.sort(key=lambda ln: ln.book, reverse=True)  # 비상장은 차익 0 → 장부 큰 순
    land.sort(key=lambda ln: ln.gain_high, reverse=True)

    out = []
    if eq:
        out.append(ReportSection("상장 보유지분 (종목별)", eq,
                                  intro="보수=장부 계상액, 시가=현재 KRX 종가. 차익=시가−장부."))
    if unl:
        out.append(ReportSection("비상장 지분 (근사)", unl,
                                  intro="순자산×지분율 근사 — 시장가 아님."))
    if land:
        out.append(ReportSection(
            "투자부동산·토지 (필지별)", land,
            intro="보수=취득원가(장부) ~ 공시지가×면적 ~ 시가보정. 🔴=검토대기(매칭 저신뢰), range 상한에만 반영."))
    return out


def build_company_report(pipe, stock_code: str, *, bsns_year=None,
                         compute_catalyst: bool = False, land_assets_by_corp=None):
    """파이프라인 per-item 평가로 CompanyReport 조립 — 종목별·필지별 [장부 ~ 시가] range + 신뢰도."""
    bsns_year = bsns_year or str(date.today().year - 1)
    try:
        cc = pipe.dart.corp_code_for_stock(stock_code)
    except Exception:
        cc = None
    if not cc:
        return None
    land_assets = (land_assets_by_corp or {}).get(cc)
    nav, valuations, review_queue, _unresolved = pipe.value_company(
        cc, stock_code, bsns_year=bsns_year,
        land_assets=land_assets, compute_catalyst=compute_catalyst,
    )
    return CompanyReport(
        name=nav.name, stock_code=nav.stock_code or stock_code,
        market_cap=nav.market_cap, reported_book_equity=nav.reported_book_equity,
        sections=sections_from_valuations(valuations, review_queue),
        catalyst_score=nav.catalyst_score, value_trap=nav.catalyst_value_trap,
        source=f"DART 사업보고서({bsns_year}) · 자동집계",
        asof=nav.as_of_date,
        footnotes=[
            "장부·자본총계 = 별도(OFS) 기준. 시세 = 현재 KRX 종가.",
            "상장지분 range: S0 보수=장부 계상액(취득시점), S1·S2=현재 시가 (2시점).",
            "토지 range: S0=취득원가(장부), S1=공시지가×면적, S2=시가보정. 🔴 검토대기 필지는 S2 상한에만 가산(불확실).",
            "비상장은 순자산×지분율 근사, 시장가 아님.",
        ],
    )
