"""리포트/스크린/API로그 → pandas DataFrame (순수, Streamlit 비의존 — 테스트 가능).

Streamlit 앱이 이 프레임을 ``st.dataframe`` 로 그린다. UI는 얇게, 표 만드는 로직은 여기서.
금액은 모두 '억'(÷1e8)으로 표기 — KR(원)·JP(엔) 공통(억=1e8). 통화 구분은 report.currency.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

import pandas as pd

from .markdown_report import CompanyReport, scenario_navs

_CONF = {"high": "🟢", "med": "🟡", "low": "🔴"}
_EOK = Decimal("100000000")  # 1억


def _eok(x: Optional[Decimal]) -> Optional[float]:
    return None if x is None else round(float(x) / float(_EOK), 1)


def overview_metrics(report: CompanyReport) -> dict:
    """상단 요약 — 시총·기준자본·nav_discount 범위(억/퍼센트)."""
    scen = scenario_navs(report)
    nds = [nd for *_, nd in scen if nd is not None]
    return {
        "시가총액(억)": _eok(report.market_cap),
        report.equity_label + "(억)": _eok(report.reported_book_equity),
        "nav_discount 하한": (round(float(min(nds)) * 100, 1) if nds else None),
        "nav_discount 상한": (round(float(max(nds)) * 100, 1) if nds else None),
    }


def scenario_frame(report: CompanyReport) -> pd.DataFrame:
    """케이스별 종합 NAV — S0 보수 / S1 추정하한 / S2 추정상한."""
    rows = []
    for name, nav, nd in scenario_navs(report):
        rows.append({
            "시나리오": name,
            "revalued_nav(억)": _eok(nav),
            "nav_discount(%)": (None if nd is None else round(float(nd) * 100, 1)),
        })
    return pd.DataFrame(rows)


def section_frames(report: CompanyReport) -> list:
    """자산 섹션별 [(title, intro, DataFrame)] — 종목/필지별 range + 신뢰도(🟢🟡🔴)."""
    out = []
    for s in report.sections:
        rows = []
        for ln in s.lines:
            rows.append({
                "자산": ln.label,
                "장부가(억)": _eok(ln.book),
                "추정하한(억)": _eok(ln.est_low),
                "추정상한(억)": _eok(ln.est_high),
                "차익하한(억)": _eok(ln.gain_low),
                "차익상한(억)": _eok(ln.gain_high),
                "신뢰": _CONF.get(ln.confidence, "🟡"),
                "비고": ln.note or "",
            })
        out.append((s.title, s.intro, pd.DataFrame(rows)))
    return out


def screen_value_frame(results: list) -> pd.DataFrame:
    """value_screen 출력 [(ScreenMetrics, ok)] → 1차 스크린 표(✅/✗)."""
    def f(x: Optional[Decimal], dec: int = 2) -> Optional[float]:
        return None if x is None else round(float(x), dec)

    rows = []
    for m, ok in results:
        rows.append({
            "종목": m.name,
            "코드": m.stock_code,
            "PBR": f(m.pbr),
            "자기자본비율(%)": (None if m.equity_ratio is None else round(float(m.equity_ratio) * 100, 1)),
            "PER": f(m.per),
            "창업": m.founded_year,
            "통과": "✅" if ok else "✗",
        })
    return pd.DataFrame(rows)


def api_calls_frame(recorder) -> pd.DataFrame:
    """RequestRecorder.calls → 요약 표(출처·상태·소요·캐시·URL). 원문 미리보기는 앱에서 별도 표시."""
    rows = []
    for i, c in enumerate(getattr(recorder, "calls", []) or [], start=1):
        status = "캐시" if c.cache_hit else ("실패" if not c.ok else str(c.status))
        rows.append({
            "#": i,
            "출처": c.source,
            "상태": status,
            "ms": (None if c.cache_hit else c.elapsed_ms),
            "URL": c.url,
        })
    return pd.DataFrame(rows)
