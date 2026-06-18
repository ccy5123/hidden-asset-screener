"""자산가치주 1차 스크린 (책 1단계) — PBR·자기자본비율·PER·창업연도로 후보 압축.

증권사 앱의 'PBR 0.5 이하 + 자기자본비율 60% 이상' 스크리닝을 자동화한다. 데이터:
시총=KRX, 지배주주지분·자본총계·자산총계·순이익=DART 연결(CFS), 설립연도=기업개황(est_dt).
순수 계산/필터는 입력만 의존(테스트 가능); value_screen 이 파이프라인 소스로 수집한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

PBR_PRECISION = Decimal("0.0001")


@dataclass
class ScreenMetrics:
    name: str
    stock_code: str
    market_cap: Optional[Decimal]
    equity_controlling: Optional[Decimal]  # 지배주주지분 (PBR 분모)
    equity_total: Optional[Decimal]        # 자본총계 (자기자본비율 분자)
    assets_total: Optional[Decimal]        # 자산총계
    net_income: Optional[Decimal]          # 당기순이익(지배)
    founded_year: Optional[int]
    pbr: Optional[Decimal] = None
    equity_ratio: Optional[Decimal] = None
    per: Optional[Decimal] = None


def _ratio(num: Optional[Decimal], den: Optional[Decimal]) -> Optional[Decimal]:
    if num is None or den is None or den <= 0:
        return None
    return (num / den).quantize(PBR_PRECISION)


def compute_screen_metrics(
    *, name: str, stock_code: str, market_cap, equity_controlling, equity_total,
    assets_total, net_income, founded_year,
) -> ScreenMetrics:
    return ScreenMetrics(
        name=name, stock_code=stock_code, market_cap=market_cap,
        equity_controlling=equity_controlling, equity_total=equity_total,
        assets_total=assets_total, net_income=net_income, founded_year=founded_year,
        pbr=_ratio(market_cap, equity_controlling),       # 시총 / 지배주주지분
        equity_ratio=_ratio(equity_total, assets_total),  # 자본총계 / 자산총계
        per=_ratio(market_cap, net_income),               # 시총 / 순이익 (적자 → None)
    )


def passes_value_screen(
    m: ScreenMetrics, *,
    pbr_max: Optional[Decimal] = Decimal("0.5"),
    equity_ratio_min: Optional[Decimal] = Decimal("0.6"),
    per_max: Optional[Decimal] = None,
    founded_before: Optional[int] = None,
) -> bool:
    """책 기본값: PBR≤0.5, 자기자본비율≥60%. per_max·founded_before는 옵션. None 지표는 탈락."""
    if pbr_max is not None and (m.pbr is None or m.pbr > pbr_max):
        return False
    if equity_ratio_min is not None and (m.equity_ratio is None or m.equity_ratio < equity_ratio_min):
        return False
    if per_max is not None and (m.per is None or m.per > per_max):  # 적자(per None) → 수익성 탈락
        return False
    if founded_before is not None and (m.founded_year is None or m.founded_year > founded_before):
        return False
    return True


def value_screen(pipe, stock_codes, *, bsns_year=None, **thresholds):
    """각 종목의 ScreenMetrics + 통과여부. (pipe.dart / pipe.price_provider 사용)"""
    bsns_year = bsns_year or str(date.today().year - 1)
    out = []
    for sc in stock_codes:
        try:
            cc = pipe.dart.corp_code_for_stock(sc)
        except Exception:
            cc = None
        if not cc:
            continue
        company = pipe.dart.get_company(cc)
        eq_ctrl, eq_total, assets, ni = pipe.dart.get_screen_financials(cc, bsns_year)
        m = compute_screen_metrics(
            name=(company.name if company else sc), stock_code=sc,
            market_cap=pipe.price_provider.get_market_cap(sc),
            equity_controlling=eq_ctrl, equity_total=eq_total, assets_total=assets, net_income=ni,
            founded_year=(company.establishment_year if company else None),
        )
        out.append((m, passes_value_screen(m, **thresholds)))
    return out
