"""SPEC-IPNOTE-001 — get_investment_property_fair_value 통합 (fake session, no network)."""

import io
import zipfile
from decimal import Decimal

from asset_play.cache import CacheStore
from asset_play.config import Config
from asset_play.sources.dart_client import DartClient

from .fakes import FakeResponse, FakeSession

_DISC = (
    "_ifrs-full_MeasurementAxis_ifrs-full_"
    "NotMeasuredAtFairValueInStatementOfFinancialPositionButForWhichFairValueIsDisclosedMember"
)
_AX = "_ifrs-full_TypesOfInvestmentPropertyAxis_"
_SEP_L = "_ifrs-full_SeparateMember" + _DISC + _AX + "ifrs-full_LandMember"
_SEP_B = "_ifrs-full_SeparateMember" + _DISC + _AX + "ifrs-full_BuildingsMember"


def _doc_xml() -> str:
    c = [
        f'<TE ACODE="ifrs-full_InvestmentProperty" ACONTEXT="CFY{_SEP_L}">331,337,332</TE>',
        f'<TE ACODE="ifrs-full_InvestmentProperty" ACONTEXT="CFY{_SEP_B}">228,612,548</TE>',
        f'<TE ACODE="entity00101628_FairValueOfInvestmentProperty" ACONTEXT="CFY{_SEP_L}">745,317,499</TE>',
        f'<TE ACODE="entity00101628_FairValueOfInvestmentProperty" ACONTEXT="CFY{_SEP_B}">228,612,548</TE>',
    ]
    return "<TABLE>" + "".join(c) + "</TABLE>"


def _zip(xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc.xml", xml.encode("utf-8"))
    return buf.getvalue()


def _make_handler(bs_amount: str = "559949880000", annual=True):
    def handler(url, params):
        if "list.json" in url:
            lst = (
                [{"report_nm": "사업보고서 (2025.12)", "rcept_no": "R1", "rcept_dt": "20260318"}]
                if annual else []
            )
            return FakeResponse(json_data={"status": "000", "list": lst})
        if "document.xml" in url:
            return FakeResponse(content=_zip(_doc_xml()))
        if "fnlttSinglAcntAll.json" in url:
            return FakeResponse(json_data={"status": "000", "list": [
                {"sj_div": "BS", "account_nm": "투자부동산", "thstrm_amount": bs_amount}]})
        return FakeResponse(json_data={"status": "013"})

    return handler


def _dart(handler):
    return DartClient(Config(dart_api_key="k"), session=FakeSession(handler=handler), cache=CacheStore())


def test_ipfv_extracts_and_reconciles_thousand_won():
    ip = _dart(_make_handler()).get_investment_property_fair_value("00101628", "2025")
    assert ip is not None
    assert ip.reconciled is True
    assert ip.unit_multiplier == 1000
    assert ip.land_book == Decimal("331337332000")    # 천원 → 원
    assert ip.land_fair == Decimal("745317499000")
    assert ip.land_gain == Decimal("413980167000")    # 4,139.8억


def test_ipfv_none_when_no_annual_report():
    ip = _dart(_make_handler(annual=False)).get_investment_property_fair_value("X", "2025")
    assert ip is None


def test_ipfv_not_reconciled_blocks_autoinject():
    # BS 투자부동산이 주석과 안 맞으면 reconciled=False → 자동주입 금지 신호
    ip = _dart(_make_handler(bs_amount="12345")).get_investment_property_fair_value("X", "2025")
    assert ip is not None and ip.reconciled is False


def test_ipfv_cached_second_call_no_session_hit():
    handler = _make_handler()
    dart = _dart(handler)
    dart.get_investment_property_fair_value("00101628", "2025")
    calls_after_first = len(dart.session.calls)
    dart.get_investment_property_fair_value("00101628", "2025")  # cache hit
    assert len(dart.session.calls) == calls_after_first  # no new external calls
