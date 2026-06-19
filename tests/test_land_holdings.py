"""토지 소재지 명세 파서 — 사업보고서 '생산설비>토지' 표에서 소재지(주소)+장부가 추출 (pure)."""

from decimal import Decimal

from asset_play.sources.dart_document import parse_land_holdings

# 경방 2025 사업보고서의 실제 '토지(유형자산 및 투자부동산)' 표 (HTML 구조 보존)
_KB_DOC = """
<P>(1) 토지(유형자산 및 투자부동산)</P>
<TABLE><TBODY><TR><TD></TD><TD>(단위 : 백만원)</TD></TR></TBODY></TABLE>
<TABLE BORDER="1" WIDTH="759"><TBODY>
<TR><TD ROWSPAN="2">사업장</TD><TD ROWSPAN="2">소재지</TD><TD COLSPAN="4">토 지</TD></TR>
<TR><TD>기초</TD><TD>증가</TD><TD>감소</TD><TD>기말</TD></TR>
<TR><TD>본사</TD><TD>서울영등포구 영중로 15 외</TD><TD>459,124</TD><TD>-</TD><TD>-</TD><TD>459,124</TD></TR>
<TR><TD COLSPAN="2">토지합계</TD><TD>459,124</TD><TD>-</TD><TD>-</TD><TD>459,124</TD></TR>
</TBODY></TABLE>
"""


def test_parse_land_holdings_kyungbang():
    hs = parse_land_holdings(_KB_DOC)
    assert len(hs) == 1                      # 데이터 1행 (헤더·합계 제외)
    h = hs[0]
    assert h.office == "본사"
    assert "영등포" in h.location and "영중로 15" in h.location   # 주소(타임스퀘어)
    assert h.book_value == Decimal("459124") * Decimal("1000000")  # 459,124백만 = 4,591억


def test_parse_land_holdings_skips_total_and_header():
    # 합계/헤더 행은 제외 — 데이터 행만
    hs = parse_land_holdings(_KB_DOC)
    assert all("합계" not in h.office and "소재지" not in h.location for h in hs)


def test_parse_land_holdings_unit_thousand():
    doc = _KB_DOC.replace("(단위 : 백만원)", "(단위 : 천원)")
    assert parse_land_holdings(doc)[0].book_value == Decimal("459124") * Decimal("1000")


def test_parse_land_holdings_none_when_absent():
    assert parse_land_holdings("<P>아무 표도 없음</P>") == []


def test_parse_land_holdings_multi_site():
    doc = _KB_DOC.replace(
        "<TR><TD COLSPAN=\"2\">토지합계</TD>",
        "<TR><TD>경방베트남</TD><TD>베트남 빈증</TD><TD>40,000</TD><TD>-</TD><TD>-</TD><TD>45,000</TD></TR>"
        "<TR><TD COLSPAN=\"2\">토지합계</TD>",
    )
    hs = parse_land_holdings(doc)
    locs = {h.office: h.location for h in hs}
    assert "본사" in locs and locs["경방베트남"] == "베트남 빈증"
    assert hs[1].book_value == Decimal("45000") * Decimal("1000000")  # 기말(마지막 숫자)
