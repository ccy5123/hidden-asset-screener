"""SPEC-UNLISTED-001 — 비상장 지분 근사 (Tier 3, 후순위).

순자산 × 지분율 (신뢰도 低). 재무 미공시 시 취득원가 유지 + 미평가 플래그.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from ..domain.enums import ConfidenceGrade
from ..domain.models import EquityHolding, UnlistedValuation, ValuationSnapshot


def value_unlisted_holding(
    holding: EquityHolding,
    *,
    net_assets: Optional[Decimal] = None,
    as_of: Optional[date] = None,
    source: str = "DART:순자산×지분율",
) -> UnlistedValuation:
    as_of = as_of or holding.as_of_date or date.today()

    # AC-2: no financials → keep acquisition cost, flag unvalued.
    if net_assets is None or holding.ownership_ratio is None:
        return UnlistedValuation(
            asset_id=holding.stable_id(),
            investee_name=holding.investee_name,
            book_value=holding.book_value,
            market_value=holding.book_value,
            unrealized_gain=Decimal(0),
            confidence=ConfidenceGrade.LOW,
            unvalued=True,
            snapshot=ValuationSnapshot(
                source="acquisition_cost",
                as_of_date=as_of,
                method="취득원가 유지 (재무 미공시)",
                market_value=holding.book_value,
            ),
            warnings=["미평가: 피투자사 재무 미공시"],
        )

    # AC-1: 순자산 × 지분율, 신뢰도 低.
    market_value = (net_assets * holding.ownership_ratio / Decimal(100)).quantize(Decimal(1))
    return UnlistedValuation(
        asset_id=holding.stable_id(),
        investee_name=holding.investee_name,
        book_value=holding.book_value,
        market_value=market_value,
        unrealized_gain=market_value - holding.book_value,
        confidence=ConfidenceGrade.LOW,
        unvalued=False,
        snapshot=ValuationSnapshot(
            source=source,
            as_of_date=as_of,
            method="순자산 × 지분율",
            market_value=market_value,
            assumptions={"net_assets": str(net_assets), "ownership_ratio": str(holding.ownership_ratio)},
        ),
    )
