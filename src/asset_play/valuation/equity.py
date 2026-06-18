"""SPEC-EQUITY-001 — 보유 상장지분 숨은가치 (Tier 1 ⭐).

Invariants enforced here:
- #1 별도 FS only: consolidated holdings never reach valuation (they net out).
- #4 units already normalized to 원 upstream (DartClient → to_won).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable, Optional

from ..domain.enums import ConfidenceGrade, FSType, LiquidityClass
from ..domain.models import EquityHolding, EquityValuation, ValuationSnapshot
from ..exceptions import InvariantViolation
from ..sources.krx import PriceProvider

# Relative divergence between shares×price and ownership×market_cap above which we
# attach a mismatch warning (AC-4) — but never stop.
_MISMATCH_TOLERANCE = Decimal("0.05")

StockResolver = Callable[[EquityHolding], Optional[str]]


@dataclass
class EquityValuationResult:
    valuations: list[EquityValuation] = field(default_factory=list)
    tier3_queue: list[EquityHolding] = field(default_factory=list)  # unlisted → SPEC-UNLISTED
    warnings: list[str] = field(default_factory=list)


def select_separate_fs_holdings(
    separate: Optional[list[EquityHolding]],
    consolidated: Optional[list[EquityHolding]] = None,
) -> list[EquityHolding]:
    """Choose 별도(separate) FS holdings (AC-3). Consolidated is only a fallback warning case."""
    if separate:
        return separate
    if consolidated:
        raise InvariantViolation(
            "only consolidated FS holdings available; equity NAV requires separate FS "
            "(연결은 내부 상계로 사라짐)"
        )
    return []


def _is_listed(holding: EquityHolding, stock_code: Optional[str]) -> bool:
    if holding.is_investee_listed is True:
        return True
    if holding.is_investee_listed is False:
        return False
    return bool(stock_code)


def value_equity_holdings(
    holdings: list[EquityHolding],
    price_provider: PriceProvider,
    *,
    resolve_stock_code: Optional[StockResolver] = None,
    investee_market_cap: Optional[Callable[[str], Optional[Decimal]]] = None,
    as_of: Optional[date] = None,
) -> EquityValuationResult:
    """Value listed holdings precisely; route unlisted ones to the Tier-3 queue.

    ``미실현이익 = 보유주식수 × 피투자사_현재가 − 장부가액``  (AC-1)
    """
    result = EquityValuationResult()
    as_of = as_of or price_provider.as_of()

    for h in holdings:
        if h.fs_type == FSType.CONSOLIDATED:
            raise InvariantViolation(
                f"consolidated-FS holding reached equity valuation: {h.investee_name}"
            )

        stock_code = h.investee_stock_code or (resolve_stock_code(h) if resolve_stock_code else None)

        if not _is_listed(h, stock_code):
            result.tier3_queue.append(h)  # AC-2 → SPEC-UNLISTED-001
            continue

        price = price_provider.get_close_price(stock_code) if stock_code else None
        mcap = investee_market_cap(stock_code) if (investee_market_cap and stock_code) else None

        market_value: Optional[Decimal] = None
        method = ""
        mv_by_shares = h.shares * price if (h.shares is not None and price is not None) else None
        mv_by_ratio = (
            (h.ownership_ratio / Decimal(100)) * mcap
            if (h.ownership_ratio is not None and mcap is not None)
            else None
        )

        if mv_by_shares is not None:
            market_value = mv_by_shares
            method = "보유주식수 × 피투자사_현재가"
        elif mv_by_ratio is not None:
            market_value = mv_by_ratio
            method = "지분율 × 피투자사_시가총액"

        warnings: list[str] = []
        # AC-4: cross-check; warn (don't stop) on divergence.
        if mv_by_shares is not None and mv_by_ratio is not None and mv_by_ratio != 0:
            divergence = abs(mv_by_shares - mv_by_ratio) / abs(mv_by_ratio)
            if divergence > _MISMATCH_TOLERANCE:
                warnings.append(
                    f"지분율·주식수 불일치: shares-based {mv_by_shares} vs "
                    f"ratio-based {mv_by_ratio} (Δ={divergence:.1%})"
                )

        if market_value is None:
            result.warnings.append(
                f"listed but unpriced (no price/market-cap): {h.investee_name} ({stock_code})"
            )
            continue

        snapshot = ValuationSnapshot(
            source=price_provider.source_name,
            as_of_date=price_provider.as_of(as_of),
            method=method,
            unit_price=price,
            market_value=market_value,
        )
        result.valuations.append(
            EquityValuation(
                asset_id=h.stable_id(),
                investee_name=h.investee_name,
                investee_stock_code=stock_code,
                book_value=h.book_value,
                market_value=market_value,
                unrealized_gain=market_value - h.book_value,
                confidence=ConfidenceGrade.HIGH,
                liquidity=LiquidityClass.from_purpose(h.investment_purpose),  # AC-5
                snapshot=snapshot,
                warnings=warnings,
            )
        )

    return result
