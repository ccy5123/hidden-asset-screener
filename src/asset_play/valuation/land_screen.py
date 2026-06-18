"""SPEC-LAND-001 — 토지 1차 스크리닝 (Tier 2-①).

Proxy signals only (no precise NAV): exclude revaluation-model firms, prefer
investment-property fair-value notes when present, and flag suspiciously low book/area.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from ..config import Config
from ..domain.enums import MeasurementModel
from ..domain.models import Company, LandAsset, LandScreenResult, ValuationSnapshot


def _percentile(values: list[Decimal], q: Decimal) -> Optional[Decimal]:
    """Lower-interpolated quantile. ``q`` in [0,1]."""
    pts = sorted(v for v in values if v is not None)
    if not pts:
        return None
    if len(pts) == 1:
        return pts[0]
    pos = q * Decimal(len(pts) - 1)
    lo = int(pos)
    frac = pos - Decimal(lo)
    if lo + 1 >= len(pts):
        return pts[-1]
    return pts[lo] + (pts[lo + 1] - pts[lo]) * frac


def screen_land(
    company: Company,
    land_assets: list[LandAsset],
    *,
    peer_book_per_sqm: Optional[list[Decimal]] = None,
    as_of: Optional[date] = None,
    config: Optional[Config] = None,
) -> LandScreenResult:
    config = config or Config()
    model = company.land_measurement_model
    if model == MeasurementModel.UNKNOWN and land_assets:
        # fall back to the measurement model carried on the parcels
        models = {la.measurement_model for la in land_assets}
        if models == {MeasurementModel.REVALUATION}:
            model = MeasurementModel.REVALUATION
        elif MeasurementModel.COST in models:
            model = MeasurementModel.COST

    result = LandScreenResult(
        corp_code=company.corp_code,
        stock_code=company.stock_code,
        name=company.name,
        measurement_model=model,
    )

    # AC-1: revaluation-model firms are excluded as candidates (already at fair value).
    if model == MeasurementModel.REVALUATION:
        result.excluded = True
        result.exclude_reason = "재평가모형 (토지가 이미 공정가치)"
        return result

    total_book = sum((la.book_value for la in land_assets), Decimal(0))
    result.total_land_book_value = total_book

    areas = [la.area_sqm for la in land_assets if la.area_sqm is not None]
    total_area = sum(areas, Decimal(0)) if areas else None
    result.total_area_sqm = total_area
    if total_area and total_area > 0:
        result.book_per_sqm = (total_book / total_area).quantize(Decimal("0.01"))

    if company.market_cap and company.market_cap > 0:
        result.land_to_marketcap_ratio = (total_book / company.market_cap).quantize(
            Decimal("0.0001")
        )

    # AC-2: investment-property fair value note → use the market value immediately.
    ip_book = sum((la.book_value for la in land_assets if la.fair_value is not None), Decimal(0))
    ip_fair = sum((la.fair_value for la in land_assets if la.fair_value is not None), Decimal(0))
    if ip_fair > 0:
        result.investment_property_fair_value = ip_fair
        result.investment_property_gain = ip_fair - ip_book
        result.flags.append("투자부동산 공정가치 주석 사용")
        result.snapshot = ValuationSnapshot(
            source="DART:투자부동산 공정가치 주석",
            as_of_date=as_of or (company.as_of_date or date.today()),
            method="투자부동산 공정가치 − 장부가",
            market_value=ip_fair,
        )

    # AC-3: book/area in the bottom X% of peers → "노후 취득 의심".
    aged = False
    if result.book_per_sqm is not None and peer_book_per_sqm:
        cutoff = _percentile(peer_book_per_sqm, config.land_aged_acquisition_percentile)
        if cutoff is not None and result.book_per_sqm <= cutoff:
            aged = True
            result.flags.append("노후 취득 의심 (면적당 장부가 하위)")

    # Signal score (proxy strength) + shortlisting decision.
    score = Decimal(0)
    ratio = result.land_to_marketcap_ratio
    if ratio is not None and ratio >= config.land_to_marketcap_threshold:
        score += min(ratio / config.land_to_marketcap_threshold, Decimal(2)) * Decimal("0.4")
    if aged:
        score += Decimal("0.4")
    if result.investment_property_gain and result.investment_property_gain > 0:
        score += Decimal("0.4")
    result.signal_score = score.quantize(Decimal("0.001"))

    result.shortlisted = bool(
        (ratio is not None and ratio >= config.land_to_marketcap_threshold)
        or aged
        or (result.investment_property_gain and result.investment_property_gain > 0)
    )
    return result
