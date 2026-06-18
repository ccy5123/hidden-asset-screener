"""SPEC-IPNOTE-001 — 사업보고서 document.xml 투자부동산 공정가치 주석 파서 (pure).

DART document.xml은 XBRL 태그가 박힌 HTML이다. 투자부동산 공정가치 주석의 각 값 cell은
``<TE ACODE="..." ACONTEXT="...">금액</TE>`` 형태로, 표준 IFRS taxonomy 컨텍스트를 담는다:

- 장부가:   ACODE == ``ifrs-full_InvestmentProperty``
- 공정가치: ACODE contains ``FairValueOfInvestmentProperty``
- 기준:     ACONTEXT contains ``_SeparateMember_`` (별도) / ``_ConsolidatedMember_`` (연결)
- 유형:     ACONTEXT contains ``_LandMember`` / ``_BuildingsMember``

표준 태그라 회사 무관. 단, 표시 금액의 **단위**(천원/백만원)는 표 헤더에만 있어 회사마다
다르므로, 별도 BS 투자부동산 총액(원)과 **대사**해 자동 검출한다(unit_multiplier_by_reconcile).
대사 실패 시 단위를 추정하지 않는다(날조 금지) — 호출부가 사람 검토로 폴백.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

# 값 cell: <TE ...> 또는 <TD ...> 안의 ACODE/ACONTEXT + 내부 텍스트(금액)
_CELL = re.compile(r"<T[DE]\b([^>]*)>(.*?)</T[DE]>", re.IGNORECASE | re.DOTALL)
_ACODE = re.compile(r'ACODE="([^"]*)"')
_ACONTEXT = re.compile(r'ACONTEXT="([^"]*)"')
_INT = re.compile(r"-?\d+")

# 공정가치 '공시' 표를 유일하게 식별하는 measurement-axis 멤버. ifrs-full_InvestmentProperty
# 태그는 변동표(기초/취득원가/감가상각)에도 쓰이므로, 이 마커가 없으면 그 값을 잘못 집는다.
_DISCLOSED = "NotMeasuredAtFairValueInStatementOfFinancialPositionButForWhichFairValueIsDisclosedMember"


def _to_decimal(text: str) -> Optional[Decimal]:
    s = re.sub(r"<[^>]+>", "", text).strip().replace(",", "")
    return Decimal(s) if _INT.fullmatch(s) else None


def parse_ip_fair_value_cells(doc_text: str) -> dict:
    """별도(OFS) 투자부동산 토지/건물의 장부가·공정가치를 **표 단위 Decimal**로 추출.

    연결(_ConsolidatedMember_)은 무시. 슬롯이 없으면 None. 동일 주석 반복 시 첫 값 채택.
    반환: {"land_book", "land_fair", "building_book", "building_fair"}
    """
    out: dict = {"land_book": None, "land_fair": None, "building_book": None, "building_fair": None}
    for m in _CELL.finditer(doc_text):
        attrs, inner = m.group(1), m.group(2)
        acode_m, actx_m = _ACODE.search(attrs), _ACONTEXT.search(attrs)
        if not acode_m or not actx_m:
            continue
        acode, actx = acode_m.group(1), actx_m.group(1)
        if "_SeparateMember_" not in actx:  # 별도만 (연결 제외)
            continue
        if _DISCLOSED not in actx:  # 공정가치 공시표만 (변동표/원가표 제외)
            continue
        is_land = "_LandMember" in actx
        is_building = "_BuildingsMember" in actx
        if not (is_land or is_building):
            continue
        is_book = acode == "ifrs-full_InvestmentProperty"
        is_fair = "FairValueOfInvestmentProperty" in acode
        if not (is_book or is_fair):
            continue
        val = _to_decimal(inner)
        if val is None:
            continue
        key = ("land" if is_land else "building") + ("_book" if is_book else "_fair")
        if out[key] is None:  # 첫 값 우선 (반복 블록은 동일)
            out[key] = val
    return out


def unit_multiplier_by_reconcile(
    land_book: Optional[Decimal],
    building_book: Optional[Decimal],
    bs_investment_property_won: Optional[Decimal],
    *,
    tol: Decimal = Decimal("0.02"),
) -> Optional[int]:
    """표 단위 (토지+건물 장부) × u ≈ 별도 BS 투자부동산(원) 인 배수 u∈{1,1e3,1e6} 검출.

    대사되는 u가 없으면 None — 단위를 추정하지 않는다(1000배 오류 방지가 핵심).
    """
    if bs_investment_property_won is None or bs_investment_property_won <= 0:
        return None
    table_total = (land_book or Decimal(0)) + (building_book or Decimal(0))
    if table_total <= 0:
        return None
    for u in (1, 1000, 1_000_000):
        diff = abs(table_total * u - bs_investment_property_won) / bs_investment_property_won
        if diff < tol:
            return u
    return None


@dataclass
class InvestmentPropertyFairValue:
    """별도(OFS) 투자부동산 토지/건물 장부가·공정가치 (원 단위). ``reconciled`` = 단위 BS 대사 성공."""

    land_book: Decimal       # 원
    land_fair: Decimal       # 원
    building_book: Optional[Decimal]
    building_fair: Optional[Decimal]
    unit_multiplier: int
    reconciled: bool
    basis: str = "OFS"

    @property
    def land_gain(self) -> Decimal:
        return self.land_fair - self.land_book
