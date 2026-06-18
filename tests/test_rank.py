"""SPEC-NAV-001 ranking."""

from decimal import Decimal

from asset_play.aggregate.rank import rank_by_net_surplus, rank_by_surplus_ratio
from asset_play.domain.models import NAVResult


def _nav(name, net, ratio=None):
    return NAVResult(
        corp_code=name, name=name, net_surplus=Decimal(net),
        surplus_ratio=Decimal(ratio) if ratio is not None else None,
    )


def test_rank_by_net_surplus_desc():
    results = [_nav("a", "100"), _nav("b", "300"), _nav("c", "200")]
    ranked = rank_by_net_surplus(results)
    assert [r.name for r in ranked] == ["b", "c", "a"]


def test_rank_by_surplus_ratio_none_last():
    results = [_nav("a", "1", "0.5"), _nav("b", "1", None), _nav("c", "1", "0.9")]
    ranked = rank_by_surplus_ratio(results)
    assert [r.name for r in ranked] == ["c", "a", "b"]
