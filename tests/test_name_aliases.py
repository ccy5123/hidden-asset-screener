"""Name-alias DB: packaged defaults + user-supplied file extend resolution (data-driven)."""

import json

from asset_play.config import Config
from asset_play.sources.dart_client import DartClient, load_name_aliases, normalize_corp_name


def test_packaged_defaults_loaded():
    transliterations, _names = load_name_aliases()
    # seed includes the conglomerate transliterations (data, not code)
    assert transliterations["엘지"] == "LG"
    assert transliterations["엘에스"] == "LS"
    assert normalize_corp_name("엘지전자(주)") == "LG전자"


def test_user_alias_file_extends_resolution(tmp_path):
    alias = tmp_path / "aliases.json"
    alias.write_text(
        json.dumps(
            {
                "transliterations": {"테스트브랜드": "TB"},
                "names": {"이상한이름(주)": "099999"},
            }
        ),
        encoding="utf-8",
    )
    d = DartClient(Config(name_aliases_path=alias))
    d._index(
        [
            {"corp_code": "x", "corp_name": "TB전자", "stock_code": "088888"},
            {"corp_code": "y", "corp_name": "무관회사", "stock_code": "099999"},
            {"corp_code": "z", "corp_name": "LG전자", "stock_code": "066570"},
        ]
    )
    # user transliteration: 테스트브랜드 → TB
    assert d.stock_code_for_name("테스트브랜드전자(주)") == "088888"
    # user explicit name override → stock code
    assert d.stock_code_for_name("이상한이름(주)") == "099999"
    # packaged defaults still apply alongside the user file
    assert d.stock_code_for_name("엘지전자(주)") == "066570"
