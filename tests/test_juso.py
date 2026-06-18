"""JusoClient — 행안부 도로명주소 검색API로 도로명/지번 → 정확 PNU 구성."""

from asset_play.sources.juso import JusoClient


def _payload(juso):
    return {"results": {"common": {"errorCode": "0", "errorMessage": "정상"}, "juso": juso}}


def test_parse_pnu_from_juso_response():
    # 영암 신북공단로10 → 갈곡리 41-2 (전남방직 영암공장)
    p = _payload([{"jibunAddr": "전라남도 영암군 신북면 갈곡리 41-2",
                   "admCd": "4683033024", "mtYn": "0", "lnbrMnnm": "41", "lnbrSlno": "2"}])
    assert JusoClient._parse_pnu(p) == "4683033024100410002"


def test_parse_pnu_mountain_and_zero_subnumber():
    p = _payload([{"admCd": "1234567890", "mtYn": "1", "lnbrMnnm": "5", "lnbrSlno": "0"}])
    assert JusoClient._parse_pnu(p) == "1234567890200050000"  # 산 → 필지구분 2


def test_parse_pnu_error_or_empty_returns_none():
    assert JusoClient._parse_pnu({"results": {"common": {"errorCode": "E0001"}, "juso": []}}) is None
    assert JusoClient._parse_pnu(_payload([])) is None
    assert JusoClient._parse_pnu({}) is None
