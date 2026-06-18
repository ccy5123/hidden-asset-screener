"""SPEC-CORE-001 — retry/backoff, quota (AC-4), and cache-hit-skips-network (AC-2)."""

import pytest

from asset_play.config import Config
from asset_play.cache import CacheStore
from asset_play.exceptions import QuotaExceededError, SourceError
from asset_play.sources.base import HttpSource, QuotaTracker

from .fakes import FakeResponse, FakeSession


def _config(**kw):
    return Config(max_retries=3, backoff_base_seconds=0.0, **kw)


def test_retries_then_succeeds_on_5xx():
    session = FakeSession(
        [
            FakeResponse(status_code=500),
            FakeResponse(status_code=503),
            FakeResponse(status_code=200, json_data={"ok": True}),
        ]
    )
    src = HttpSource(_config(), session=session, sleep=lambda s: None)
    assert src.get_json("http://x") == {"ok": True}
    assert len(session.calls) == 3


def test_gives_up_after_max_retries():
    session = FakeSession(handler=lambda u, p: FakeResponse(status_code=500))
    src = HttpSource(_config(), session=session, sleep=lambda s: None)
    with pytest.raises(SourceError):
        src.get_json("http://x")
    assert len(session.calls) == 4  # 1 + 3 retries


def test_connection_error_retried():
    state = {"n": 0}

    def handler(url, params):
        state["n"] += 1
        if state["n"] < 2:
            return ConnectionError("boom")
        return FakeResponse(status_code=200, json_data={"ok": 1})

    src = HttpSource(_config(), session=FakeSession(handler=handler), sleep=lambda s: None)
    assert src.get_json("http://x") == {"ok": 1}


def test_quota_exceeded_raises_without_call():
    session = FakeSession([FakeResponse(json_data={})])
    src = HttpSource(_config(), session=session, quota=QuotaTracker(0), sleep=lambda s: None)
    with pytest.raises(QuotaExceededError):
        src.get_json("http://x")
    assert session.calls == []  # never reached the network


def test_quota_increments_until_exhausted():
    session = FakeSession(handler=lambda u, p: FakeResponse(json_data={"ok": 1}))
    src = HttpSource(_config(), session=session, quota=QuotaTracker(2), sleep=lambda s: None)
    src.get_json("http://x")
    src.get_json("http://x")
    with pytest.raises(QuotaExceededError):
        src.get_json("http://x")
    assert len(session.calls) == 2


def test_cache_hit_skips_network():
    session = FakeSession([FakeResponse(json_data={"v": 1})])  # only ONE response available
    cache = CacheStore()
    src = HttpSource(_config(), session=session, cache=cache, sleep=lambda s: None)
    first = src.get_json("http://x", {"a": 1}, namespace="ns", cache_key="k")
    second = src.get_json("http://x", {"a": 1}, namespace="ns", cache_key="k")
    assert first == second == {"v": 1}
    assert len(session.calls) == 1  # AC-2: second call served from cache
    assert cache.hits >= 1
