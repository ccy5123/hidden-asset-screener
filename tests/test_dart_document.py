"""SPEC-IPNOTE-001 — 투자부동산 공정가치 주석 XBRL 파서 + 단위 대사 (pure, no network)."""

from decimal import Decimal

from asset_play.sources.dart_document import (
    InvestmentPropertyFairValue,
    parse_ip_fair_value_cells,
    unit_multiplier_by_reconcile,
)

_DISC = "_ifrs-full_MeasurementAxis_ifrs-full_NotMeasuredAtFairValueInStatementOfFinancialPositionButForWhichFairValueIsDisclosedMember"
_SEP = "_ifrs-full_SeparateMember" + _DISC  # 별도 + 공정가치 공시표 컨텍스트
_CON = "_ifrs-full_ConsolidatedMember" + _DISC
_LAND = "_ifrs-full_TypesOfInvestmentPropertyAxis_ifrs-full_LandMember"
_BLDG = "_ifrs-full_TypesOfInvestmentPropertyAxis_ifrs-full_BuildingsMember"
_BOOK = "ifrs-full_InvestmentProperty"
_FAIR = "entity00101628_FairValueOfInvestmentPropertyWhenEntityAppliesCostModelOfDisclosure"
# 변동표(원가/감가상각) cell — ifrs-full_InvestmentProperty 지만 DISCLOSED 마커 없음 → 무시되어야 함
_MOVE = "_ifrs-full_SeparateMember_ifrs-full_TypesOfInvestmentPropertyAxis_ifrs-full_BuildingsMember"


def _cell(acode: str, actx: str, value: str) -> str:
    return f'<TE ACODE="{acode}" ACONTEXT="CFY2025eFY{actx}">{value}</TE>'


# 경방 실제 태그 형식을 그대로 모사. (1) 연결 토지 공정가치는 다른 값(999...)으로 넣어 별도(745...)
# 선택을 검증. (2) 변동표 건물 장부(364...)를 넣어 공시표(228...)만 고르는지(변동표 무시) 검증.
FIXTURE = "<TABLE><TR>" + "".join([
    _cell(_BOOK, _MOVE, "364,258,223"),         # 변동표 건물 — 무시되어야 함 (DISCLOSED 마커 없음)
    _cell(_BOOK, _SEP + _LAND, "331,337,332"),
    _cell(_BOOK, _SEP + _BLDG, "228,612,548"),
    _cell(_FAIR, _SEP + _LAND, "745,317,499"),
    _cell(_FAIR, _SEP + _BLDG, "228,612,548"),
    _cell(_FAIR, _CON + _LAND, "999,999,999"),  # 연결 — 무시되어야 함
]) + "</TR></TABLE>"


def test_parse_picks_separate_land_building_ignores_consolidated():
    p = parse_ip_fair_value_cells(FIXTURE)
    assert p["land_book"] == Decimal("331337332")
    assert p["land_fair"] == Decimal("745317499")  # 별도, 연결 999... 아님
    assert p["building_book"] == Decimal("228612548")
    assert p["building_fair"] == Decimal("228612548")


def test_parse_none_slots_when_no_fair_value():
    p = parse_ip_fair_value_cells("<TABLE></TABLE>")
    assert p["land_fair"] is None and p["land_book"] is None


def test_parse_land_only_company():
    xml = "<TABLE>" + _cell(_BOOK, _SEP + _LAND, "100,000") + _cell(_FAIR, _SEP + _LAND, "250,000") + "</TABLE>"
    p = parse_ip_fair_value_cells(xml)
    assert p["land_book"] == Decimal("100000") and p["land_fair"] == Decimal("250000")
    assert p["building_book"] is None and p["building_fair"] is None


def test_unit_reconcile_detects_thousand_won():
    # (331,337,332 + 228,612,548) 천원 == 559,949,880,000 원
    u = unit_multiplier_by_reconcile(
        Decimal("331337332"), Decimal("228612548"),
        bs_investment_property_won=Decimal("559949880000"),
    )
    assert u == 1000


def test_unit_reconcile_detects_million_won():
    u = unit_multiplier_by_reconcile(
        Decimal("331337"), Decimal("228612"),
        bs_investment_property_won=Decimal("559949000000"),
    )
    assert u == 1_000_000


def test_unit_reconcile_none_when_no_match():
    u = unit_multiplier_by_reconcile(
        Decimal("331337332"), Decimal("228612548"),
        bs_investment_property_won=Decimal("123456789"),
    )
    assert u is None


def test_unit_reconcile_none_when_bs_missing():
    assert unit_multiplier_by_reconcile(Decimal("1"), Decimal("1"), None) is None


def test_dataclass_land_gain():
    ip = InvestmentPropertyFairValue(
        land_book=Decimal("331337332000"), land_fair=Decimal("745317499000"),
        building_book=None, building_fair=None, unit_multiplier=1000, reconciled=True,
    )
    assert ip.land_gain == Decimal("413980167000")
    assert ip.basis == "OFS"
