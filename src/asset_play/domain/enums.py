"""Enumerations shared across the domain."""

from __future__ import annotations

from enum import Enum


class Market(str, Enum):
    """Listing market. Mapped from DART ``corp_cls``."""

    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    KONEX = "KONEX"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_dart_corp_cls(cls, corp_cls: str | None) -> "Market":
        return {
            "Y": cls.KOSPI,
            "K": cls.KOSDAQ,
            "N": cls.KONEX,
            "E": cls.OTHER,
        }.get((corp_cls or "").strip().upper(), cls.UNKNOWN)


class MeasurementModel(str, Enum):
    """Land/PP&E measurement model. Revaluation-model firms are excluded as candidates."""

    COST = "원가"
    REVALUATION = "재평가"
    UNKNOWN = "불명"


class FSType(str, Enum):
    """Financial-statement basis. Equity holdings MUST use SEPARATE (invariant)."""

    SEPARATE = "separate"  # 별도재무제표 (OFS)
    CONSOLIDATED = "consolidated"  # 연결재무제표 (CFS)


class AssetClass(str, Enum):
    EQUITY = "equity"  # 상장 보유 지분
    LAND = "land"  # 토지
    INVESTMENT_PROPERTY = "investment_property"  # 투자부동산 (공정가치 주석)
    UNLISTED_EQUITY = "unlisted_equity"  # 비상장 지분 (근사)
    OTHER = "other"


class LiquidityClass(str, Enum):
    """자산이 시장가치로 '풀릴 수 있는' 성격 (SPEC-NAV rev.3 AC-5)."""

    REALIZABLE = "realizable"  # 투자부동산·단순투자 지분 → 매각/환원으로 unlock 가능
    RECOGNITION_ONLY = "recognition"  # 영업용 토지·경영참여 지분 → 인식으로만 re-rating
    UNKNOWN = "unknown"

    @classmethod
    def from_purpose(cls, purpose: str | None) -> "LiquidityClass":
        """타법인출자현황 출자목적(invstmnt_purps) → 분류. 단순투자=realizable, 경영참여=recognition."""
        if not purpose:
            return cls.UNKNOWN
        p = str(purpose).replace(" ", "")
        if "단순" in p:
            return cls.REALIZABLE
        if "경영" in p or "참여" in p or "참가" in p:
            return cls.RECOGNITION_ONLY
        return cls.UNKNOWN


class Tier(str, Enum):
    TIER1 = "tier1"  # 완전 자동 (상장 지분)
    TIER2 = "tier2"  # 반자동 (토지)
    TIER3 = "tier3"  # 근사 (비상장)


class ConfidenceGrade(str, Enum):
    """Data-confidence grade. HIGH=高, MEDIUM=中, LOW=低.

    Use :meth:`combine` to aggregate per-asset grades into an overall grade —
    the overall grade is never better than its weakest input (NAV AC-2).
    """

    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"

    @property
    def rank(self) -> int:
        return {ConfidenceGrade.HIGH: 3, ConfidenceGrade.MEDIUM: 2, ConfidenceGrade.LOW: 1}[self]

    @classmethod
    def combine(cls, *grades: "ConfidenceGrade | None") -> "ConfidenceGrade | None":
        present = [g for g in grades if g is not None]
        if not present:
            return None
        return min(present, key=lambda g: g.rank)
