"""SPEC-IPNOTE-001 — 투자부동산 공정가치 주석 XBRL 파서 + BS 대사 (pure, no network).

분리형(경방: 토지/건물 분리) + 합산형(BYC: 단일 멤버) 두 공시 형태를 모두 포괄하는지 검증.
"""

from decimal import Decimal

from asset_play.sources.dart_document import (
    InvestmentPropertyFairValue,
    parse_ip_pairs,
    resolve_ip_fair_value,
)

_DISC = (
    "_ifrs-full_MeasurementAxis_ifrs-full_"
    "NotMeasuredAtFairValueInStatementOfFinancialPositionButForWhichFairValueIsDisclosedMember"
)
_AX = "_ifrs-full_TypesOfInvestmentPropertyAxis_"


def _cell(acode: str, actx: str, value: str) -> str:
    return f'<TE ACODE="{acode}" ACONTEXT="{actx}">{value}</TE>'


# --- 분리형 (경방): 별도 + 토지/건물 분리, 단위 천원 ---------------------------------- #
def _sep(member: str) -> str:
    return "CFY2025eFY_ifrs-full_SeparateMember" + _DISC + _AX + member


SPLIT_DOC = "<TABLE>" + "".join([
    # 변동표 건물(공정가치 짝 없음) — 쌍이 안 되어 배제되어야 함
    _cell("ifrs-full_InvestmentProperty",
          "CFY2025eFY_ifrs-full_SeparateMember" + _AX + "ifrs-full_BuildingsMember", "364,258,223"),
    _cell("ifrs-full_InvestmentProperty", _sep("ifrs-full_LandMember"), "331,337,332"),
    _cell("ifrs-full_InvestmentProperty", _sep("ifrs-full_BuildingsMember"), "228,612,548"),
    _cell("entity_FairValueOfInvestmentProperty", _sep("ifrs-full_LandMember"), "745,317,499"),
    _cell("entity_FairValueOfInvestmentProperty", _sep("ifrs-full_BuildingsMember"), "228,612,548"),
    # 연결 토지 공정가치(다른 값) — 별도 우선이라 무시되어야 함
    _cell("entity_FairValueOfInvestmentProperty",
          "CFY2025eFY_ifrs-full_ConsolidatedMember" + _DISC + _AX + "ifrs-full_LandMember", "999"),
]) + "</TABLE>"


def test_split_reconciles_and_keeps_land_detail():
    pairs = parse_ip_pairs(SPLIT_DOC)
    # 별도 BS 투자부동산 = (토지331,337,332 + 건물228,612,548) 천원 = 559,949,880,000 원
    r = resolve_ip_fair_value(pairs, Decimal("559949880000"))
    assert r is not None and r.reconciled and r.unit_multiplier == 1000 and r.basis == "OFS"
    assert r.ip_book == Decimal("559949880000")
    assert r.ip_fair == Decimal("973930047000")
    assert r.land_book == Decimal("331337332000")   # 토지 분리값 보존
    assert r.land_fair == Decimal("745317499000")
    assert r.inject_book == Decimal("331337332000")  # 주입은 토지 우선
    assert r.inject_fair == Decimal("745317499000")
    assert r.ip_gain == Decimal("413980167000")


# --- 합산형 (BYC): 연결=별도, 토지/건물 미분리, 회사 고유 개념, 단위 원 --------------- #
_BYC_CTX = (
    "CFY2025eFY_ifrs-full_ConsolidatedMember_ifrs-full_TypesOfInvestmentPropertyAxis_"
    "entity00122579_HeadquaterAndBusinessCenterMember"
)
COMBINED_DOC = "<TABLE>" + "".join([
    _cell("ifrs-full_InvestmentPropertyCompleted", _BYC_CTX, "438,972,652,335"),
    _cell("entity00122579_InvestmentPropertyCompletedAtFairValue", _BYC_CTX, "1,278,020,277,403"),
]) + "</TABLE>"


def test_combined_single_member_reconciles_unit_one():
    pairs = parse_ip_pairs(COMBINED_DOC)
    r = resolve_ip_fair_value(pairs, Decimal("438972652335"))  # BS 투자부동산 (원)
    assert r is not None and r.reconciled and r.unit_multiplier == 1 and r.basis == "CFS"
    assert r.ip_book == Decimal("438972652335")
    assert r.ip_fair == Decimal("1278020277403")
    assert r.land_book is None and r.inject_book == Decimal("438972652335")  # 분리 없음 → 합산 주입
    assert r.ip_gain == Decimal("839047625068")


def test_movement_table_book_excluded_when_unpaired():
    # 변동표 건물(364...)만 있고 공정가치 짝이 없으면 후보에서 빠져 토지+건물 대사가 정상.
    pairs = parse_ip_pairs(SPLIT_DOC)
    assert all(
        not (g["book"] == Decimal("364258223") and g["fair"] is not None)
        for g in pairs["OFS"].values()
    )


def test_none_when_no_bs_anchor():
    assert resolve_ip_fair_value(parse_ip_pairs(COMBINED_DOC), None) is None


def test_none_when_no_candidate_reconciles():
    assert resolve_ip_fair_value(parse_ip_pairs(SPLIT_DOC), Decimal("123456789")) is None


def test_prior_year_cells_ignored():
    pfy = "<TABLE>" + _cell(
        "ifrs-full_InvestmentProperty",
        "PFY2024eFY_ifrs-full_SeparateMember" + _AX + "ifrs-full_LandMember", "111,111",
    ) + "</TABLE>"
    assert parse_ip_pairs(pfy)["OFS"] == {}


def test_dataclass_ip_gain():
    ip = InvestmentPropertyFairValue(
        ip_book=Decimal("100"), ip_fair=Decimal("250"),
        land_book=None, land_fair=None, unit_multiplier=1, basis="OFS",
    )
    assert ip.ip_gain == Decimal("150") and ip.inject_book == Decimal("100")
