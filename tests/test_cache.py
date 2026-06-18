"""SPEC-CORE-001 AC-2 — caching (hit counters, TTL, invalidation)."""

from asset_play.cache import CacheStore


def test_set_get_and_hit_counters():
    store = CacheStore()
    assert store.get("ns", "missing") is None
    assert store.misses == 1

    store.set("ns", "k", "v")
    assert store.get("ns", "k") == "v"
    assert store.hits == 1


def test_json_roundtrip():
    store = CacheStore()
    store.set_json("ns", "k", {"a": 1, "b": [2, 3]})
    assert store.get_json("ns", "k") == {"a": 1, "b": [2, 3]}


def test_ttl_expiry(monkeypatch):
    store = CacheStore()
    clock = [1000.0]
    monkeypatch.setattr(store, "_now", lambda: clock[0])
    store.set("ns", "k", "v", ttl=10)
    assert store.get("ns", "k") == "v"
    clock[0] = 1011.0
    assert store.get("ns", "k") is None  # expired → treated as miss


def test_invalidate():
    store = CacheStore()
    store.set("ns", "k", "v")
    store.invalidate("ns", "k")
    assert store.get("ns", "k") is None
