"""SPEC-NAV-001 — 통합 집계.

미실현이익_총(세전) = Σ(지분 + 토지 + 투자부동산 + 기타)
net_surplus(세후)   = 미실현이익_총 × (1 − 법인세율)
surplus_ratio       = net_surplus / 시가총액

Invariant #2 (이중계상 금지): each ``asset_id`` is counted at most once across all classes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional, Protocol

from ..domain.enums import AssetClass, ConfidenceGrade
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
    )


def aggregate_nav(
    company: Company,
    valuations: Iterable[_ValuationLike],
    *,
    tax_rate: Decimal = Decimal("0.22"),
    correction_factor: Optional[Decimal] = None,
    review_queue_count: int = 0,
    as_of: Optional[date] = None,
) -> NAVResult:
    by_class: dict[AssetClass, ClassAggregate] = {}
    evidence: list[ValuationSnapshot] = []
    warnings: list[str] = []
    seen: set[str] = set()

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

        snap = getattr(v, "snapshot", None)
        if snap is not None:
            evidence.append(snap)

    total_pretax = sum((a.unrealized_gain for a in by_class.values()), Decimal(0))
    net_surplus = (total_pretax * (Decimal(1) - tax_rate)).quantize(Decimal(1))

    surplus_ratio: Optional[Decimal] = None
    if company.market_cap and company.market_cap > 0:
        surplus_ratio = (net_surplus / company.market_cap).quantize(Decimal("0.000001"))

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
        net_surplus=net_surplus,
        surplus_ratio=surplus_ratio,
        overall_confidence=overall,
        assumptions=assumptions,
        evidence=evidence,
        warnings=warnings,
        review_queue_count=review_queue_count,
    )
