"""SPEC-NAV-001 rev.3 — 통합 NAV·괴리·랭킹.

total_pretax  = Σ(class.unrealized_gain)              # asset_id 이중계상 제거
total_posttax = total_pretax × (1 − t)  if > 0 else total_pretax   # 손실엔 세금환급 가정 안 함
revalued_nav  = reported_book_equity(별도 OFS 자본총계) + total_posttax
nav_discount  = 1 − market_cap / revalued_nav         # >0 → NAV 대비 할인(쌈); 1차 신호
surplus_ratio = total_posttax / market_cap            # 보조

OFS-basis 통일: 자기자본·보유지분·토지 surplus 모두 별도(OFS) 기준. 연결 지배주주지분을
쓰면 자회사 잉여가 두 번 잡혀 revalued_nav 과대 → nav_discount 과대(가짜 '싼' 신호).
한계: 자회사 내부에 묻힌 토지·자산은 look-through 안 됨(보수적 누락; 다층 지주사는 별도 처리).

Invariant #2 (이중계상 금지): each ``asset_id`` is counted at most once across all classes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional, Protocol

from ..domain.enums import AssetClass, ConfidenceGrade, LiquidityClass
from ..domain.models import ClassAggregate, Company, NAVResult, ValuationSnapshot


class _ValuationLike(Protocol):
    asset_class: AssetClass
    asset_id: str
    book_value: Decimal
    market_value: Decimal
    unrealized_gain: Decimal
    confidence: Optional[ConfidenceGrade]


@dataclass
class SimpleValuation:
    """Duck-typed valuation item for ad-hoc entries (e.g. investment property)."""

    asset_class: AssetClass
    asset_id: str
    book_value: Decimal
    market_value: Decimal
    unrealized_gain: Decimal
    confidence: Optional[ConfidenceGrade] = None
    snapshot: Optional[ValuationSnapshot] = None
    liquidity: LiquidityClass = LiquidityClass.UNKNOWN


def make_investment_property_item(
    asset_id: str, book_value: Decimal, fair_value: Decimal, snapshot: Optional[ValuationSnapshot] = None
) -> SimpleValuation:
    return SimpleValuation(
        asset_class=AssetClass.INVESTMENT_PROPERTY,
        asset_id=asset_id,
        book_value=book_value,
        market_value=fair_value,
        unrealized_gain=fair_value - book_value,
        confidence=ConfidenceGrade.MEDIUM,
        snapshot=snapshot,
        liquidity=LiquidityClass.REALIZABLE,  # 투자부동산 공정가치 → 매각/환원 가능
    )


def aggregate_nav(
    company: Company,
    valuations: Iterable[_ValuationLike],
    *,
    tax_rate: Decimal = Decimal("0.22"),
    correction_factor: Optional[Decimal] = None,
    reported_book_equity: Optional[Decimal] = None,
    review_queue_count: int = 0,
    as_of: Optional[date] = None,
) -> NAVResult:
    by_class: dict[AssetClass, ClassAggregate] = {}
    evidence: list[ValuationSnapshot] = []
    warnings: list[str] = []
    seen: set[str] = set()
    realizable = Decimal(0)  # AC-5: 실현가능 세전 소계
    recognition = Decimal(0)  # 인식형 + 분류불명(보수) 세전 소계
    unknown_count = 0

    for v in valuations:
        if v.asset_id in seen:  # invariant #2: dedup across classes
            warnings.append(f"이중계상 방지: 자산 '{v.asset_id}' 중복 제외")
            continue
        seen.add(v.asset_id)

        agg = by_class.setdefault(v.asset_class, ClassAggregate(asset_class=v.asset_class))
        agg.book_value += v.book_value
        agg.market_value += v.market_value
        agg.unrealized_gain += v.unrealized_gain
        agg.item_count += 1
        agg.confidence = ConfidenceGrade.combine(agg.confidence, getattr(v, "confidence", None))

        liq = getattr(v, "liquidity", LiquidityClass.UNKNOWN)
        if liq == LiquidityClass.REALIZABLE:
            realizable += v.unrealized_gain
        else:  # recognition-only + unknown(보수 처리)
            recognition += v.unrealized_gain
            if liq == LiquidityClass.UNKNOWN:
                unknown_count += 1

        snap = getattr(v, "snapshot", None)
        if snap is not None:
            evidence.append(snap)

    if unknown_count:
        warnings.append(
            f"분류 불명 {unknown_count}건 → recognition-only 보수 처리 (manual_override)"
        )

    total_pretax = sum((a.unrealized_gain for a in by_class.values()), Decimal(0))
    # AC-2: corporate tax applies only to a net gain; a net loss assumes no tax refund.
    if total_pretax > 0:
        total_posttax = (total_pretax * (Decimal(1) - tax_rate)).quantize(Decimal(1))
    else:
        total_posttax = total_pretax

    surplus_ratio: Optional[Decimal] = None
    if company.market_cap and company.market_cap > 0:
        surplus_ratio = (total_posttax / company.market_cap).quantize(Decimal("0.000001"))

    # revalued NAV = 별도(OFS) 자기자본 + 세후 미실현이익 (same OFS basis as the surplus).
    revalued_nav: Optional[Decimal] = None
    nav_discount: Optional[Decimal] = None
    if reported_book_equity is not None:
        revalued_nav = reported_book_equity + total_posttax
        if revalued_nav <= 0:  # AC-3: guard divide-by-(≤0); discount is undefined.
            warnings.append(f"revalued_nav ≤ 0 ({revalued_nav}); nav_discount N/A")
        elif company.market_cap and company.market_cap > 0:
            nav_discount = (Decimal(1) - company.market_cap / revalued_nav).quantize(
                Decimal("0.000001")
            )

    overall = ConfidenceGrade.combine(*(a.confidence for a in by_class.values()))

    assumptions = {
        "tax_rate": str(tax_rate),
        "net_surplus_formula": "미실현이익_총 × (1 − 법인세율)",
        "surplus_ratio_denominator": "시가총액",
    }
    if correction_factor is not None:
        assumptions["land_price_correction_factor"] = str(correction_factor)

    return NAVResult(
        corp_code=company.corp_code,
        stock_code=company.stock_code,
        name=company.name,
        market=company.market,
        market_cap=company.market_cap,
        as_of_date=as_of or company.as_of_date,
        by_class=by_class,
        total_unrealized_pretax=total_pretax,
        tax_rate=tax_rate,
        total_unrealized_posttax=total_posttax,
        net_surplus=total_posttax,
        reported_book_equity=reported_book_equity,
        revalued_nav=revalued_nav,
        nav_discount=nav_discount,
        realizable_surplus=realizable,
        recognition_only_surplus=recognition,
        surplus_ratio=surplus_ratio,
        overall_confidence=overall,
        assumptions=assumptions,
        evidence=evidence,
        warnings=warnings,
        review_queue_count=review_queue_count,
    )
