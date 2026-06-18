"""SPEC-CORE-001 — DART corpCode (AC-1), status handling, holdings, model classifier (AC-3)."""

from decimal import Decimal

import pytest

from asset_play.cache import CacheStore
from asset_play.config import Config
from asset_play.domain.enums import FSType, Market, MeasurementModel
from asset_play.exceptions import ConfigError, QuotaExceededError
from asset_play.sources.dart_client import DartClient, classify_land_measurement_model

from .fakes import FakeResponse, FakeSession, make_corpcode_zip


def _dart(session, cache=None):
    return DartClient(Config(dart_api_key="testkey"), session=session, cache=cache or CacheStore())


def test_sync_corp_codes_builds_mapping():  # AC-1
    zip_bytes = make_corpcode_zip(
        [
            ("00126380", "삼성전자", "005930"),
            ("00164742", "현대자동차", "005380"),
            ("00999999", "비상장에이", ""),  # unlisted → no stock_code
        ]
    )
    dart = _dart(FakeSession([FakeResponse(content=zip_bytes)]))
    rows = dart.sync_corp_codes()

    assert len(rows) == 3
    assert dart.corp_code_for_stock("005930") == "00126380"
    assert dart.stock_code_for_name("현대자동차") == "005380"
    assert dart.corp_code_for_name("비상장에이") == "00999999"
    assert dart.stock_code_for_name("비상장에이") is None
    assert dart.is_listed_corp("00126380") is True
    assert dart.is_listed_corp("00999999") is False


def test_get_company_maps_market_and_caches():  # also CORE AC-2
    payload = {"status": "000", "corp_name": "삼성전자", "stock_code": "005930", "corp_cls": "Y"}
    session = FakeSession([FakeResponse(json_data=payload)])  # only one response
    dart = _dart(session)

    c1 = dart.get_company("00126380")
    c2 = dart.get_company("00126380")  # served from cache
    assert c1.market == Market.KOSPI
    assert c1.stock_code == "005930"
    assert c2 == c1
    assert len(session.calls) == 1


def test_get_company_quota_status_raises():
    session = FakeSession([FakeResponse(json_data={"status": "020", "message": "한도초과"})])
    with pytest.raises(QuotaExceededError):
        _dart(session).get_company("00126380")


def test_get_company_key_error_raises_config():
    session = FakeSession([FakeResponse(json_data={"status": "010", "message": "등록되지않은키"})])
    with pytest.raises(ConfigError):
        _dart(session).get_company("00126380")


def test_get_other_corp_investments_parses_separate_fs():
    payload = {
        "status": "000",
        "list": [
            {
                "inv_prm": "상장자회사",
                "trmend_blce_qy": "1,000,000",
                "trmend_blce_qota_rt": "30.0",
                "trmend_blce_acntbk_amount": "10,000,000,000",
                "frst_acqs_amount": "8,000,000,000",
                "invstmnt_purps": "경영참가",
            }
        ],
    }
    holdings = _dart(FakeSession([FakeResponse(json_data=payload)])).get_other_corp_investments(
        "00126380", "2024"
    )
    assert len(holdings) == 1
    h = holdings[0]
    assert h.investee_name == "상장자회사"
    assert h.shares == Decimal("1000000")
    assert h.book_value == Decimal("10000000000")
    assert h.investment_purpose == "경영참가"  # 출자목적 parsed (AC-5)
    assert h.fs_type == FSType.SEPARATE  # invariant #1


def test_get_other_corp_investments_drops_summary_rows():
    # 타법인출자현황 includes a 합계/소계 total row that must NOT be ingested as a holding.
    payload = {
        "status": "000",
        "list": [
            {
                "inv_prm": "상장자회사",
                "trmend_blce_qy": "1,000,000",
                "trmend_blce_qota_rt": "30.0",
                "trmend_blce_acntbk_amount": "10,000,000,000",
                "frst_acqs_amount": "8,000,000,000",
            },
            {"inv_prm": "합 계", "trmend_blce_acntbk_amount": "10,000,000,000"},
            {"inv_prm": "소계", "trmend_blce_acntbk_amount": "10,000,000,000"},
        ],
    }
    holdings = _dart(FakeSession([FakeResponse(json_data=payload)])).get_other_corp_investments(
        "x", "2024"
    )
    assert [h.investee_name for h in holdings] == ["상장자회사"]


def test_no_data_status_returns_empty():
    session = FakeSession([FakeResponse(json_data={"status": "013", "message": "데이터없음"})])
    assert _dart(session).get_other_corp_investments("x", "2024") == []


def test_get_disclosures_returns_list():  # SPEC-CATALYST-001
    payload = {"status": "000", "list": [{"report_nm": "주식소각결정", "rcept_dt": "20250724"}]}
    dart = _dart(FakeSession([FakeResponse(json_data=payload)]))
    disc = dart.get_disclosures("00126380", "20240101", "20251231")
    assert disc[0]["report_nm"] == "주식소각결정"


def test_separate_total_equity_uses_ofs_bs():  # SPEC-NAV-001 rev.3 AC-4
    payload = {
        "status": "000",
        "list": [
            {"sj_div": "BS", "account_nm": "자본총계", "thstrm_amount": "500,000,000,000"},
            {"sj_div": "SCE", "account_nm": "자본총계", "thstrm_amount": "999,000,000,000"},
        ],
    }
    session = FakeSession([FakeResponse(json_data=payload)])
    dart = _dart(session)
    assert dart.get_separate_total_equity("00126380", "2024") == Decimal("500000000000")  # BS, not SCE
    _url, params = session.calls[0]
    assert params["fs_div"] == "OFS"  # separate FS, not consolidated


@pytest.mark.parametrize(
    "text,expected",
    [
        ("유형자산 중 토지는 재평가모형으로 측정한다.", MeasurementModel.REVALUATION),
        ("토지를 포함한 유형자산은 원가모형을 적용한다.", MeasurementModel.COST),
        ("당사는 종전 재평가모형에서 당기부터 원가모형으로 변경하여 측정한다.", MeasurementModel.COST),
        ("특이사항 없음", MeasurementModel.UNKNOWN),
        (None, MeasurementModel.UNKNOWN),
    ],
)
def test_classify_land_measurement_model(text, expected):  # AC-3
    assert classify_land_measurement_model(text) == expected
