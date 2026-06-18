"""SPEC-LAND-002 — 토지 정밀 NAV (Tier 2-②, human-in-loop).

``토지_추정시가 = Σ(필지면적 × 개별공시지가 × 시가보정계수)``

Invariant: a parcel is auto-confirmed into ``valuations`` only when address→PNU and
공시지가 both resolve and confidence ≥ threshold. Everything else goes to ``review_queue``
— never silently dropped, never auto-confirmed (AC-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from ..config import Config
from ..domain.enums import ConfidenceGrade
from ..domain.models import LandAsset, PreciseLandValuation, ReviewQueueItem, ValuationSnapshot
from ..sources.molit import LandPriceProvider
from ..sources.vworld import Geocoder


@dataclass
class LandPreciseResult:
    valuations: list[PreciseLandValuation] = field(default_factory=list)
    review_queue: list[ReviewQueueItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def value_land_precise(
    land_assets: list[LandAsset],
    geocoder: Geocoder,
    land_price_provider: LandPriceProvider,
    *,
    config: Optional[Config] = None,
    as_of: Optional[date] = None,
    min_auto_confirm: ConfidenceGrade = ConfidenceGrade.MEDIUM,
) -> LandPreciseResult:
    config = config or Config()
    result = LandPreciseResult()

    for la in land_assets:
        # 1. resolve PNU (직접 제공 우선, 실패 시 geocoder)
        pnu = la.pnu
        pnu_source = "asset"
        if not pnu and la.location_text:
            pnu = geocoder.address_to_pnu(la.location_text)
            pnu_source = "geocoder"
        if not pnu:
            result.review_queue.append(
                ReviewQueueItem(
                    holder_corp_code=la.holder_corp_code,
                    location_text=la.location_text,
                    area_sqm=la.area_sqm,
                    book_value=la.book_value,
                    reason="주소→PNU 매칭 실패",  # AC-2
                )
            )
            continue

        # 2. 면적 확인
        if la.area_sqm is None or la.area_sqm <= 0:
            result.review_queue.append(
                ReviewQueueItem(
                    holder_corp_code=la.holder_corp_code,
                    location_text=la.location_text,
                    area_sqm=la.area_sqm,
                    book_value=la.book_value,
                    reason="면적 불명",
                    raw={"pnu": pnu},
                )
            )
            continue

        # 3. 개별공시지가 조회
        price = la.official_price_per_sqm or land_price_provider.get_official_price_per_sqm(pnu)
        if price is None:
            result.review_queue.append(
                ReviewQueueItem(
                    holder_corp_code=la.holder_corp_code,
                    location_text=la.location_text,
                    area_sqm=la.area_sqm,
                    book_value=la.book_value,
                    reason="개별공시지가 조회 실패",
                    raw={"pnu": pnu},
                )
            )
            continue

        # 4. 시가보정계수 적용 (AC-3: 일관 적용 + 출처 기록)
        c = config.correction_factor_for(la.location_text)
        estimated = (la.area_sqm * price * c).quantize(Decimal(1))

        # confidence: 직접 PNU+가격 → 中, geocoded → 中(매칭 성공). 실패만 검토 큐.
        confidence = (
            ConfidenceGrade.MEDIUM
            if pnu_source == "asset" or la.official_price_per_sqm is not None
            else ConfidenceGrade.MEDIUM
        )

        if confidence.rank < min_auto_confirm.rank:
            result.review_queue.append(
                ReviewQueueItem(
                    holder_corp_code=la.holder_corp_code,
                    location_text=la.location_text,
                    area_sqm=la.area_sqm,
                    book_value=la.book_value,
                    reason=f"저신뢰 필지 ({confidence.value}) — 사람 확인 필요",
                    raw={"pnu": pnu, "estimated_market_value": str(estimated)},
                )
            )
            continue

        snapshot = ValuationSnapshot(
            source=land_price_provider.source_name,
            as_of_date=as_of or land_price_provider.as_of(),
            method="필지면적 × 개별공시지가 × 시가보정계수",
            unit_price=price,
            market_value=estimated,
            assumptions={
                "correction_factor": str(c),
                "official_price_per_sqm": str(price),
                "pnu_source": pnu_source,
                "pnu": pnu,
            },
        )
        result.valuations.append(
            PreciseLandValuation(
                asset_id=pnu,
                location_text=la.location_text,
                pnu=pnu,
                area_sqm=la.area_sqm,
                official_price_per_sqm=price,
                correction_factor=c,
                book_value=la.book_value,
                market_value=estimated,
                unrealized_gain=estimated - la.book_value,
                confidence=confidence,
                snapshot=snapshot,
            )
        )

    return result
