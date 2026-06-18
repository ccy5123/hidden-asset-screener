"""pydantic data contracts.

Money fields are ``Decimal`` and always expressed in **원** (TRUST invariant #4).
Every market value carries a :class:`ValuationSnapshot` with ``source`` + ``as_of_date``
(TRUST invariant #5: traceability).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import AssetClass, ConfidenceGrade, FSType, LiquidityClass, Market, MeasurementModel


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Inputs (collected by SPEC-CORE)
# --------------------------------------------------------------------------- #
class ValuationSnapshot(_Base):
    """A point-in-time market value with provenance. ``source`` + ``as_of_date`` required."""

    source: str
    as_of_date: date
    method: str = ""  # human-readable derivation, e.g. "shares × close"
    unit_price: Optional[Decimal] = None
    market_value: Optional[Decimal] = None  # 원
    assumptions: dict[str, str] = Field(default_factory=dict)


class Company(_Base):
    corp_code: str
    stock_code: Optional[str] = None
    name: str
    market: Market = Market.UNKNOWN
    market_cap: Optional[Decimal] = None  # 원
    shares_outstanding: Optional[Decimal] = None
    land_measurement_model: MeasurementModel = MeasurementModel.UNKNOWN
    as_of_date: Optional[date] = None


class EquityHolding(_Base):
    """A holding of another company's shares, from 타법인출자현황 (separate FS)."""

    investee_name: str
    holder_corp_code: Optional[str] = None
    investee_corp_code: Optional[str] = None
    investee_stock_code: Optional[str] = None
    is_investee_listed: Optional[bool] = None
    shares: Optional[Decimal] = None
    ownership_ratio: Optional[Decimal] = None  # percent (0–100)
    acquisition_cost: Optional[Decimal] = None  # 원
    book_value: Decimal = Decimal(0)  # 원 — 지분법 or 원가법 계상액
    accounting_method: Optional[str] = None  # "지분법" | "원가법"
    investment_purpose: Optional[str] = None  # 출자목적 (invstmnt_purps): 경영참여 / 단순투자
    fs_type: FSType = FSType.SEPARATE
    source: Optional[str] = None
    as_of_date: Optional[date] = None

    def stable_id(self) -> str:
        """Identity used for dedup (NAV invariant #2)."""
        return self.investee_corp_code or self.investee_stock_code or self.investee_name


class LandAsset(_Base):
    holder_corp_code: Optional[str] = None
    location_text: Optional[str] = None
    area_sqm: Optional[Decimal] = None
    book_value: Decimal = Decimal(0)  # 원
    land_category: Optional[str] = None  # 지목
    pnu: Optional[str] = None  # 필지고유번호 (19 digits)
    official_price_per_sqm: Optional[Decimal] = None  # 개별공시지가 (원/㎡)
    fair_value: Optional[Decimal] = None  # 투자부동산 공정가치 주석 (원)
    measurement_model: MeasurementModel = MeasurementModel.UNKNOWN


# --------------------------------------------------------------------------- #
# Valuation outputs
# --------------------------------------------------------------------------- #
class EquityValuation(_Base):
    """SPEC-EQUITY-001 result for a single listed holding."""

    asset_class: AssetClass = AssetClass.EQUITY
    asset_id: str
    investee_name: str
    investee_stock_code: Optional[str] = None
    book_value: Decimal  # 원
    market_value: Decimal  # 원
    unrealized_gain: Decimal  # 원 (market − book)
    confidence: ConfidenceGrade = ConfidenceGrade.HIGH
    liquidity: LiquidityClass = LiquidityClass.UNKNOWN  # AC-5
    snapshot: ValuationSnapshot
    warnings: list[str] = Field(default_factory=list)


class UnlistedValuation(_Base):
    """SPEC-UNLISTED-001 result (net-asset approximation)."""

    asset_class: AssetClass = AssetClass.UNLISTED_EQUITY
    asset_id: str
    investee_name: str
    book_value: Decimal  # 원
    market_value: Decimal  # 원 (approx; == book_value when unvalued)
    unrealized_gain: Decimal  # 원
    confidence: ConfidenceGrade = ConfidenceGrade.LOW
    liquidity: LiquidityClass = LiquidityClass.UNKNOWN  # AC-5
    snapshot: ValuationSnapshot
    unvalued: bool = False
    warnings: list[str] = Field(default_factory=list)


class LandScreenResult(_Base):
    """SPEC-LAND-001 first-pass screening output."""

    corp_code: str
    stock_code: Optional[str] = None
    name: str
    measurement_model: MeasurementModel = MeasurementModel.UNKNOWN
    excluded: bool = False
    exclude_reason: Optional[str] = None
    total_land_book_value: Decimal = Decimal(0)  # 원
    total_area_sqm: Optional[Decimal] = None
    land_to_marketcap_ratio: Optional[Decimal] = None
    book_per_sqm: Optional[Decimal] = None  # 원/㎡
    investment_property_fair_value: Optional[Decimal] = None  # 원
    investment_property_gain: Optional[Decimal] = None  # 원 (fair_value − book)
    signal_score: Decimal = Decimal(0)
    shortlisted: bool = False
    flags: list[str] = Field(default_factory=list)
    snapshot: Optional[ValuationSnapshot] = None


class PreciseLandValuation(_Base):
    """SPEC-LAND-002 per-parcel precise valuation (auto-confirmed parcels only)."""

    asset_class: AssetClass = AssetClass.LAND
    asset_id: str  # pnu or normalized location
    location_text: Optional[str] = None
    pnu: Optional[str] = None
    area_sqm: Optional[Decimal] = None
    official_price_per_sqm: Optional[Decimal] = None
    correction_factor: Decimal = Decimal(1)
    book_value: Decimal = Decimal(0)  # 원
    market_value: Decimal  # 원
    unrealized_gain: Decimal  # 원
    confidence: ConfidenceGrade = ConfidenceGrade.MEDIUM
    liquidity: LiquidityClass = LiquidityClass.RECOGNITION_ONLY  # 영업용 토지 → 인식형 (AC-5)
    snapshot: ValuationSnapshot


class ReviewQueueItem(_Base):
    """A parcel that could NOT be auto-confirmed (SPEC-LAND-002 invariant)."""

    holder_corp_code: Optional[str] = None
    location_text: Optional[str] = None
    area_sqm: Optional[Decimal] = None
    book_value: Decimal = Decimal(0)
    reason: str
    raw: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Aggregation (SPEC-NAV-001)
# --------------------------------------------------------------------------- #
class ClassAggregate(_Base):
    """Per asset-class roll-up within a NAVResult."""

    asset_class: AssetClass
    book_value: Decimal = Decimal(0)  # 원
    market_value: Decimal = Decimal(0)  # 원
    unrealized_gain: Decimal = Decimal(0)  # 원
    confidence: Optional[ConfidenceGrade] = None
    item_count: int = 0


class NAVResult(_Base):
    """Final per-company aggregate, ranked by ``net_surplus`` / ``surplus_ratio``."""

    corp_code: str
    stock_code: Optional[str] = None
    name: str
    market: Market = Market.UNKNOWN
    market_cap: Optional[Decimal] = None  # 원
    as_of_date: Optional[date] = None

    by_class: dict[AssetClass, ClassAggregate] = Field(default_factory=dict)
    total_unrealized_pretax: Decimal = Decimal(0)  # 원 (세전; 이중계상 제거 후)
    tax_rate: Decimal = Decimal("0.22")
    total_unrealized_posttax: Decimal = Decimal(0)  # 원 (세후; SPEC-NAV rev.3)
    net_surplus: Decimal = Decimal(0)  # = total_unrealized_posttax (alias, back-compat)
    reported_book_equity: Optional[Decimal] = None  # 별도(OFS) 자본총계 — surplus와 동일 기준
    revalued_nav: Optional[Decimal] = None  # reported_book_equity + total_unrealized_posttax
    nav_discount: Optional[Decimal] = None  # 1 − market_cap / revalued_nav (1차 신호); ≤0 NAV → None
    realizable_surplus: Decimal = Decimal(0)  # 실현가능 자산 세전 소계 (AC-5)
    recognition_only_surplus: Decimal = Decimal(0)  # 인식형 자산 세전 소계 (AC-5)
    surplus_ratio: Optional[Decimal] = None  # 보조: total_unrealized_posttax / market_cap
    overall_confidence: Optional[ConfidenceGrade] = None

    assumptions: dict[str, str] = Field(default_factory=dict)
    evidence: list[ValuationSnapshot] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    review_queue_count: int = 0
