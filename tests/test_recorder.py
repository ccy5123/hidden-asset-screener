"""API 원문 기록(tap) — 키 마스킹 + HttpSource/캐시/바이트/오류 기록, recorder 없으면 no-op.

[HARD] 키는 절대 기록되면 안 된다(mask_params). recorder가 없으면 런타임 동작 불변(no-op).
"""

import json

import pytest

from asset_play.config import Config
from asset_play.exceptions import SourceError
from asset_play.sources.base import HttpSource
from asset_play.sources.recorder import (
    RequestRecorder,
    active_recorder,
    mask_params,
    preview_text,
    use_recorder,
)


# -- pure: mask / preview ----------------------------------------------------- #
def test_mask_params_redacts_sensitive_keys():
    masked = mask_params({"crtfc_key": "SECRET", "Subscription-Key": "S", "q": "삼성", "code": "9031"})
    assert masked["crtfc_key"] == "***"
    assert masked["Subscription-Key"] == "***"
    assert masked["q"] == "삼성"          # 비민감 값은 그대로
    assert masked["code"] == "9031"
    assert mask_params(None) == {}


def test_preview_text_truncates_and_handles_types():
    assert preview_text(b"\x00\x01abc").startswith("<binary 5 bytes>")
    assert "hello" in preview_text({"hello": "world"})
    long = preview_text("x" * 9000, limit=100)
    assert long.endswith("자)") and len(long) < 200   # 잘림 표시


# -- HttpSource tap ----------------------------------------------------------- #
class _Resp:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.text = "" if payload is None else json.dumps(payload)

    def json(self):
        return self._payload


class _Session:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.resp


def _src(resp, **kw):
    s = HttpSource(Config(max_retries=0, backoff_base_seconds=0.0), session=_Session(resp), **kw)
    s.source_name = "TEST"
    return s


def test_get_json_records_call_with_masked_key():
    src = _src(_Resp(200, {"hello": "world"}))
    with use_recorder() as rec:
        data = src.get_json("https://x/api", params={"crtfc_key": "SECRET", "q": "1"})
    assert data == {"hello": "world"}
    assert len(rec.calls) == 1
    c = rec.calls[0]
    assert c.source == "TEST" and c.status == 200 and c.ok and not c.cache_hit
    assert c.params["crtfc_key"] == "***" and c.params["q"] == "1"
    assert "hello" in c.preview


def test_no_recorder_is_noop():
    src = _src(_Resp(200, {"a": 1}))
    assert src.get_json("https://x") == {"a": 1}   # 오류 없이 통과
    assert active_recorder() is None               # contextvar 누수 없음


def test_records_cache_hit_without_network(tmp_path):
    from asset_play.cache import CacheStore

    cache = CacheStore(str(tmp_path / "c.sqlite"))
    cache.set_json("ns", "k", {"cached": 1}, 999)
    # session이 500을 주지만 캐시 적중이라 호출되지 않아야 함.
    src = _src(_Resp(500), cache=cache)
    with use_recorder() as rec:
        data = src.get_json("https://x", namespace="ns", cache_key="k")
    assert data == {"cached": 1}
    assert rec.calls[0].cache_hit and rec.calls[0].status is None


def test_get_bytes_records_binary_preview():
    src = _src(_Resp(200, content=b"\x00\x01zip"))
    with use_recorder() as rec:
        assert src.get_bytes("https://x/doc") == b"\x00\x01zip"
    assert "binary" in rec.calls[0].preview


def test_records_error_then_reraises():
    class _Boom:
        def get(self, *a, **k):
            raise ConnectionError("down")

    src = HttpSource(Config(max_retries=0, backoff_base_seconds=0.0), session=_Boom())
    src.source_name = "X"
    with use_recorder() as rec, pytest.raises(SourceError):
        src.get_json("https://x")
    assert rec.calls and not rec.calls[0].ok and "ERROR" in rec.calls[0].preview


def test_recorder_max_calls_caps():
    rec = RequestRecorder(max_calls=2)
    from asset_play.sources.recorder import ApiCall

    for i in range(5):
        rec.add(ApiCall("S", "GET", "u", {}, 200, 1.0, False, "p"))
    assert len(rec.calls) == 2
