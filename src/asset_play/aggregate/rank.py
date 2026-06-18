"""SPEC-NAV-001 ranking. net_surplus 내림차순; 신뢰도 등급은 NAVResult에 노출(AC-2)."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from ..domain.models import NAVResult


def rank_by_net_surplus(results: Iterable[NAVResult], *, descending: bool = True) -> list[NAVResult]:
    return sorted(results, key=lambda r: r.net_surplus, reverse=descending)


def rank_by_surplus_ratio(results: Iterable[NAVResult], *, descending: bool = True) -> list[NAVResult]:
    """Holdco-discount signal. Companies without a market cap rank last."""
    sentinel = Decimal("-1e30") if descending else Decimal("1e30")
    return sorted(
        results,
        key=lambda r: r.surplus_ratio if r.surplus_ratio is not None else sentinel,
        reverse=descending,
    )


def rank_by_nav_discount(results: Iterable[NAVResult], *, descending: bool = True) -> list[NAVResult]:
    """Primary SPEC-NAV rev.3 signal: nav_discount desc, surplus_ratio as tie-break.

    N/A nav_discount (no 별도 자기자본, or revalued_nav ≤ 0) sorts last. confidence_grade
    travels on each NAVResult so proxy-based names aren't mistaken for precise ones (AC-6).
    """
    sentinel = Decimal("-1e30")

    def key(r: NAVResult) -> tuple[Decimal, Decimal]:
        nd = r.nav_discount if r.nav_discount is not None else sentinel
        sr = r.surplus_ratio if r.surplus_ratio is not None else sentinel
        return (nd, sr)

    return sorted(results, key=key, reverse=descending)
