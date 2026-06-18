"""Investee-name resolution against the corpCode master (SPEC-EQUITY-001).

타법인출자현황 reports investee names in Hangul with a (주) affix and footnote
markers (e.g. '엘지전자(주)'), while the corpCode master uses the Latin short form
('LG전자'). Resolution must bridge that gap or listed subsidiaries are silently
misclassified as unlisted — which zeroes out the hidden-asset signal for holdcos.
"""

from asset_play.config import Config
from asset_play.sources.dart_client import DartClient

MASTER = [
    {"corp_code": "0001", "corp_name": "LG전자", "stock_code": "066570"},
    {"corp_code": "0002", "corp_name": "LG화학", "stock_code": "051910"},
    {"corp_code": "0003", "corp_name": "LG유플러스", "stock_code": "032640"},
    {"corp_code": "0004", "corp_name": "삼성전자", "stock_code": "005930"},
    {"corp_code": "0005", "corp_name": "SK하이닉스", "stock_code": "000660"},
    {"corp_code": "0006", "corp_name": "CJ제일제당", "stock_code": "097950"},
    {"corp_code": "0007", "corp_name": "현대모비스", "stock_code": "012330"},
]


def _client() -> DartClient:
    d = DartClient(Config())
    d._index(MASTER)
    return d


def test_resolves_transliterated_listed_subsidiaries():
    d = _client()
    # 한글 음역 + (주) affix → Latin master short form
    assert d.stock_code_for_name("엘지전자(주)") == "066570"
    assert d.stock_code_for_name("(주)엘지화학") == "051910"
    assert d.stock_code_for_name("(주)엘지유플러스") == "032640"
    assert d.stock_code_for_name("에스케이하이닉스(주)") == "000660"
    assert d.stock_code_for_name("씨제이제일제당(주)") == "097950"


def test_corp_code_resolves_transliterated_names():
    d = _client()
    assert d.corp_code_for_name("(주)엘지화학") == "0002"


def test_exact_match_still_wins():
    d = _client()
    assert d.stock_code_for_name("현대모비스") == "012330"
    assert d.stock_code_for_name("삼성전자") == "005930"


def test_strip_corporate_form_only():
    d = _client()
    assert d.stock_code_for_name("삼성전자 주식회사") == "005930"


def test_unknown_name_returns_none():
    d = _client()
    assert d.stock_code_for_name("존재하지않는회사") is None


def test_resolves_ls_electric_both_spellings_and_star_footnotes():
    # Master stores LS ELECTRIC in Hangul (엘에스일렉트릭); reports spell it two ways and
    # append *1)-style footnotes (not in parentheses).
    d = DartClient(Config())
    d._index([{"corp_code": "0010", "corp_name": "엘에스일렉트릭", "stock_code": "010120"}])
    assert d.stock_code_for_name("LS일렉트릭") == "010120"  # Latin LS + Hangul 일렉트릭
    assert d.stock_code_for_name("엘에스일렉트릭(주)") == "010120"
    assert d.stock_code_for_name("LS일렉트릭*1)") == "010120"  # star-footnote stripped
    assert d.stock_code_for_name("LS전선*1)") is None  # genuinely unlisted


def test_normalize_corp_name_examples():
    from asset_play.sources.dart_client import normalize_corp_name as N

    assert N("엘지전자(주)") == N("LG전자") == "LG전자"
    assert N("(주)엘지화학") == "LG화학"
    assert N("삼성전자 주식회사") == "삼성전자"
    assert N("VAST Data, LTD.(*2)") == "VASTDATALTD"  # footnotes + punct stripped, no crash
    assert N("에이치디씨") == "HDC"  # longest-key-first beats 에이치디→HD
    assert N("에이치디현대") == "HD현대"
    assert N("(주)케이티앤지") == "KTG"
    assert N(None) == ""
    assert N("") == ""
