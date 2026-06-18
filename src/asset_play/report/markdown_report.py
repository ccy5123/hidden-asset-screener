"""Per-company Markdown 점검 보고서 — 자산유형별 케이스 range + 신뢰도(🟢🟡🔴) + 각주.

단일 점추정이 틀릴 수 있으므로(예: 도로명 오매칭, 부분소유), 각 자산을 **[보수=장부 ~ 추정시가]
range** 로 잡고, 신뢰도를 색으로 표기한다. 종합 nav_discount도 시나리오 range로 보여준다.

순수 렌더(render_markdown)와 range 로직(scenario_navs)은 입력 데이터만 의존(테스트 가능).
build_company_report 가 파이프라인 결과(NAVResult)로 데이터를 조립한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Union

from ..domain.enums import AssetClass

_CONF = {"high": "🟢", "med": "🟡", "low": "🔴"}

# 자산군 → (라벨, 신뢰도, 주석)
_CLASS_META = {
    AssetClass.EQUITY: ("상장 보유지분", "high", None),
    AssetClass.UNLISTED_EQUITY: ("비상장 지분", "med", "순자산×지분율 근사 — 시장가 아님."),
    AssetClass.INVESTMENT_PROPERTY: ("투자부동산(공정가치 주석)", "high", "회사 공시 공정가치 — 영업용 토지보다 신뢰 높음."),
    AssetClass.LAND: ("토지(공시지가 추정)", "low", "공시지가×필지전체면적 — 면적·소유분 불명으로 상한 신뢰↓."),
    AssetClass.OTHER: ("기타", "med", None),
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
        for ln in s.lines:
            if ln.note:
                o.append(f"- {_CONF.get(ln.confidence, '🟡')} **{ln.label}**: {ln.note}")
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


def build_company_report(pipe, stock_code: str, *, bsns_year=None,
                         compute_catalyst: bool = False, land_assets_by_corp=None):
    """파이프라인(NAVResult)으로 CompanyReport 조립. 자산군별 [장부 ~ 시가] 라인 + 신뢰도."""
    run = pipe.run(
        stock_codes=[stock_code], bsns_year=bsns_year,
        land_assets_by_corp=land_assets_by_corp, compute_catalyst=compute_catalyst,
    )
    if not run.results:
        return None
    nav = run.results[0]
    lines = []
    for ac, agg in nav.by_class.items():
        label, conf, note = _CLASS_META.get(ac, (str(ac), "med", None))
        lines.append(AssetLine(label=label, book=agg.book_value,
                               est_low=agg.market_value, est_high=agg.market_value,
                               confidence=conf, note=note))
    sections = (
        [ReportSection("자산군별 미실현이익", lines, intro="자산군 집계. 보수=장부, 시가=추정/관측시가.")]
        if lines else []
    )
    return CompanyReport(
        name=nav.name, stock_code=nav.stock_code or stock_code,
        market_cap=nav.market_cap, reported_book_equity=nav.reported_book_equity,
        sections=sections, catalyst_score=nav.catalyst_score, value_trap=nav.catalyst_value_trap,
        source=f"DART 사업보고서({bsns_year or '직전연도'}) · 자동집계",
        asof=nav.as_of_date,
        footnotes=[
            "장부·자본총계 = 별도(OFS) 기준. 시세 = 현재 KRX 종가.",
            "영업용 토지(설비현황) 외부추정은 신뢰↓ — 정밀값은 사람 검토 전제(--land-file).",
            "비상장은 순자산×지분율 근사, 시장가 아님.",
        ],
    )
