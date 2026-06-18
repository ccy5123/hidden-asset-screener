"""SPEC-NAV-001 ranking. net_surplus 내림차순; 신뢰도 등급은 NAVResult에 노출(AC-2)."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from ..domain.models import NAVResult


def rank_by_net_surplus(results: Iterable[NAVResult], *, descending: bool = True) -> list[NAVResult]:
    return sorted(results, key=lambda r: r.net_surplus, reverse=descending)


def rank_by_surplus_ratio(results: Iterable[NAVResult], *, descending: bool = True) -> list[NAVResult]:
    """Primary holdco-discount signal. Companies without a market cap rank last."""
    sentinel = Decimal("-1e30") if descending else Decimal("1e30")
    return sorted(
        results,
        key=lambda r: r.surplus_ratio if r.surplus_ratio is not None else sentinel,
        reverse=descending,
    )
