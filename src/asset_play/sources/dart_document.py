"""SPEC-IPNOTE-001 — 사업보고서 document.xml 투자부동산 공정가치 주석 파서 (pure).

DART document.xml은 XBRL 태그가 박힌 HTML이다. 투자부동산 공정가치 공시표의 각 값 cell은
``<TE ACODE="..." ACONTEXT="...">금액</TE>`` 형태로 IFRS taxonomy 컨텍스트를 담는다. 회사마다
공시 형태가 둘로 갈린다:

- 분리형(예: 경방): 토지/건물을 ``_LandMember``/``_BuildingsMember`` 로 나눠 장부·공정가치 공시.
- 합산형(예: BYC): 토지+건물 합산을 회사 고유 멤버로 한 줄 공시. 개념도 ``InvestmentPropertyCompleted``
  / ``...AtFairValue`` 등 회사별로 다양.

이 둘을 모두 포괄하려고, **장부·공정가치 cell을 (기준 × 컨텍스트 멤버)로 묶어 쌍(pair)을 만들고**,
그 장부 총액을 **별도 BS 투자부동산(원)과 대사**해 (a) 올바른 총액 후보와 (b) 단위(천원/백만원)를
동시에 검출한다. 대사되는 후보가 없으면 None(날조 금지) — 변동표(장부만 있고 공정가치 짝 없음)는
쌍이 안 되어 자연히 배제된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

_CELL = re.compile(r"<T[DE]\b([^>]*)>(.*?)</T[DE]>", re.IGNORECASE | re.DOTALL)
_ACODE = re.compile(r'ACODE="([^"]*)"')
_ACONTEXT = re.compile(r'ACONTEXT="([^"]*)"')
_INT = re.compile(r"-?\d+")
_SEP_TOKEN = "_ifrs-full_SeparateMember"
_CON_TOKEN = "_ifrs-full_ConsolidatedMember"


def _to_decimal(text: str) -> Optional[Decimal]:
    s = re.sub(r"<[^>]+>", "", text).strip().replace(",", "")
    return Decimal(s) if _INT.fullmatch(s) else None


def _classify(acode: str) -> Optional[str]:
    """투자부동산 장부/공정가치 cell 분류. 그 외 None."""
    a = acode.lower()
    if "investmentproperty" not in a:
        return None
    return "fair" if "fairvalue" in a else "book"


def _basis(actx: str) -> Optional[str]:
    if _SEP_TOKEN in actx:
        return "OFS"
    if _CON_TOKEN in actx:
        return "CFS"
    return None


def _member_key(actx: str) -> str:
    """기준 멤버 이후의 컨텍스트 — 같은 공시 항목의 장부·공정가치를 한 쌍으로 묶는 키."""
    for tok in (_SEP_TOKEN, _CON_TOKEN):
        i = actx.find(tok)
        if i >= 0:
            return actx[i + len(tok):]
    return actx


def parse_ip_pairs(doc_text: str) -> dict:
    """투자부동산 장부·공정가치 cell을 (기준 × 컨텍스트 멤버) 쌍으로 수집 (표 단위 Decimal).

    반환: ``{"OFS": {member_key: {"book","fair","is_land","is_building"}}, "CFS": {...}}``.
    당기(CFY)만 — 전기(PFY)·전전기는 제외.
    """
    out: dict = {"OFS": {}, "CFS": {}}
    for m in _CELL.finditer(doc_text):
        attrs, inner = m.group(1), m.group(2)
        acode_m, actx_m = _ACODE.search(attrs), _ACONTEXT.search(attrs)
        if not acode_m or not actx_m:
            continue
        acode, actx = acode_m.group(1), actx_m.group(1)
        if not actx.startswith("CFY"):  # 당기만 (전기 PFY 오염 방지)
            continue
        kind = _classify(acode)
        basis = _basis(actx)
        if kind is None or basis is None:
            continue
        val = _to_decimal(inner)
        if val is None:
            continue
        key = _member_key(actx)
        g = out[basis].setdefault(
            key, {"book": None, "fair": None,
                  "is_land": "_LandMember" in actx, "is_building": "_BuildingsMember" in actx},
        )
        if g[kind] is None:  # 같은 멤버 첫 값 우선 (반복 블록 동일)
            g[kind] = val
    return out


@dataclass
class InvestmentPropertyFairValue:
    """별도(또는 연결 폴백) 투자부동산 장부·공정가치 (원). ``land_*``는 분리공시 시에만."""

    ip_book: Decimal             # 투자부동산 총액 장부 (원)
    ip_fair: Decimal             # 투자부동산 총액 공정가치 (원)
    land_book: Optional[Decimal]  # 토지 분리값(있으면)
    land_fair: Optional[Decimal]
    unit_multiplier: int
    basis: str                   # OFS | CFS
    reconciled: bool = True

    @property
    def ip_gain(self) -> Decimal:
        return self.ip_fair - self.ip_book

    @property
    def inject_book(self) -> Decimal:
        """auto-land 주입용: 토지 분리값 우선(검증된 표시), 없으면 합산 총액."""
        return self.land_book if self.land_book is not None else self.ip_book

    @property
    def inject_fair(self) -> Decimal:
        return self.land_fair if self.land_fair is not None else self.ip_fair


def resolve_ip_fair_value(
    pairs: dict,
    bs_investment_property_won: Optional[Decimal],
    *,
    tol: Decimal = Decimal("0.02"),
) -> Optional[InvestmentPropertyFairValue]:
    """완성된 (장부,공정) 쌍 중, 장부 총액 × 단위 ≈ 별도 BS 투자부동산(원) 인 후보를 채택.

    분리형은 토지+건물 합을, 합산형은 단일 멤버를 후보로 둔다. 별도 우선, 없으면 연결(별도 BS와
    맞을 때만 성공). 대사되는 후보가 없으면 None — 단위 오판/변동표 오집/날조를 모두 차단.
    """
    if bs_investment_property_won is None or bs_investment_property_won <= 0:
        return None
    for basis in ("OFS", "CFS"):
        complete = {
            k: v for k, v in pairs.get(basis, {}).items()
            if v["book"] is not None and v["fair"] is not None
        }
        if not complete:
            continue
        candidates = []  # (book_total, fair_total, land_book, land_fair)
        split = [v for v in complete.values() if v["is_land"] or v["is_building"]]
        if any(v["is_land"] for v in split):  # 분리형: 토지+건물 합
            sb = sum((v["book"] for v in split), Decimal(0))
            sf = sum((v["fair"] for v in split), Decimal(0))
            lb = next((v["book"] for v in split if v["is_land"]), None)
            lf = next((v["fair"] for v in split if v["is_land"]), None)
            candidates.append((sb, sf, lb, lf))
        for v in complete.values():  # 합산형/단일 멤버 후보
            candidates.append((
                v["book"], v["fair"],
                v["book"] if v["is_land"] else None,
                v["fair"] if v["is_land"] else None,
            ))
        for book, fair, lb, lf in candidates:
            if book <= 0:
                continue
            for u in (1, 1000, 1_000_000):
                if abs(book * u - bs_investment_property_won) / bs_investment_property_won < tol:
                    s = Decimal(u)
                    return InvestmentPropertyFairValue(
                        ip_book=book * s, ip_fair=fair * s,
                        land_book=(lb * s if lb is not None else None),
                        land_fair=(lf * s if lf is not None else None),
                        unit_multiplier=u, basis=basis, reconciled=True,
                    )
    return None


# --------------------------------------------------------------------------- #
# 토지 소재지 명세 (사업보고서 'II. 사업의 내용 > 생산설비 > 토지') — 주소 표시용
# --------------------------------------------------------------------------- #
@dataclass
class LandHolding:
    """'토지(유형자산 및 투자부동산)' 표 한 줄 — 소재지(주소) + 토지 장부가(원).

    장부가는 토지 기말(유형자산+투자부동산 합산)로, 투자부동산 공정가치 주석(별도)과 범위가 다르다.
    위치 확인용(어디에 있나) — 含み益/NAV 계산엔 쓰지 않는다(이중계상 방지).
    """

    office: str        # 사업장 (예: 본사)
    location: str      # 소재지 (주소)
    book_value: Decimal  # 토지 장부가 (원)


_LH_NUM = re.compile(r"-?\d[\d,]*")
_LH_UNITS = {"백만원": 1_000_000, "천원": 1_000, "원": 1}


def parse_land_holdings(doc_text: str) -> list:
    """'토지(유형자산 및 투자부동산)' 표 → [LandHolding(사업장·소재지·장부가)]. 표 없으면 []."""
    anchor = doc_text.find("토지(유형자산 및 투자부동산)")
    if anchor < 0:
        return []
    seg = doc_text[anchor: anchor + 8000]
    um = re.search(r"단위\s*[:：]\s*(백만원|천원|원)", seg[:700])
    unit = _LH_UNITS.get(um.group(1), 1_000_000) if um else 1_000_000  # 토지표 관행상 백만원
    out: list = []
    for table in re.findall(r"<TABLE.*?</TABLE>", seg, re.S):
        if "소재지" not in table or "사업장" not in table:
            continue
        for tr in re.findall(r"<TR.*?</TR>", table, re.S):
            cells = [re.sub(r"<[^>]+>", "", c).strip()
                     for c in re.findall(r"<T[DH][^>]*>(.*?)</T[DH]>", tr, re.S)]
            if len(cells) < 3:
                continue
            office, location = cells[0], cells[1]
            if (not office or not location
                    or any(k in office for k in ("합계", "소계", "계", "사업장", "기초"))
                    or "소재지" in location
                    or _LH_NUM.fullmatch(location.replace(",", ""))):  # 소재지가 숫자=데이터 아님
                continue
            nums = [c.replace(",", "") for c in cells[2:] if _LH_NUM.fullmatch(c.replace(",", ""))]
            if not nums:
                continue
            out.append(LandHolding(office, location, Decimal(nums[-1]) * unit))  # 기말=마지막 숫자
        if out:
            break
    return out

