"""SPEC-ADAPTER-001 — KrAdapter delegates the full surface to DART + price provider (pure)."""

from decimal import Decimal

from asset_play.sources.adapter import KrAdapter, MarketAdapter


class _Dart:
    def corp_code_for_stock(self, sc):
        return f"corp:{sc}"

    def get_company(self, cc):
        return f"company:{cc}"

    def get_other_corp_investments(self, cc, y, r):
        return [cc, y, r]

    def stock_code_for_name(self, n):
        return f"stock:{n}"

    def corp_code_for_name(self, n):
        return f"corpname:{n}"

    def get_net_assets(self, cc, y, r):
        return Decimal("1")

    def get_separate_total_equity(self, cc, y, r):
        return Decimal("2")

    def get_screen_financials(self, cc, y):
        return (1, 2, 3, 4)

    def get_disclosures(self, cc, b, e):
        return [b, e]

    def get_investment_property_fair_value(self, cc, y):
        return f"ipfv:{cc}"


class _Price:
    def get_market_cap(self, sc):
        return Decimal("100")

    def as_of(self):
        return "asof"


def test_kradapter_satisfies_protocol_and_delegates():
    a = KrAdapter(_Dart(), _Price())
    assert isinstance(a, MarketAdapter)  # @runtime_checkable: 표면 충족
    assert a.corp_code_for_stock("000050") == "corp:000050"
    assert a.get_company("C") == "company:C"
    assert a.get_other_corp_investments("C", "2025", "11011") == ["C", "2025", "11011"]
    assert a.stock_code_for_name("경방") == "stock:경방"
    assert a.corp_code_for_name("경방") == "corpname:경방"
    assert a.get_net_assets("C", "2025", "11011") == Decimal("1")
    assert a.get_separate_total_equity("C", "2025", "11011") == Decimal("2")
    assert a.get_screen_financials("C", "2025") == (1, 2, 3, 4)
    assert a.get_disclosures("C", "20260101", "20261231") == ["20260101", "20261231"]
    assert a.get_investment_property_fair_value("C", "2025") == "ipfv:C"
    assert a.get_market_cap("000050") == Decimal("100")
    assert a.price_as_of() == "asof"


def test_pipeline_builds_kradapter_by_default():
    from asset_play.config import Config
    from asset_play.pipeline import Pipeline

    pipe = Pipeline(Config(), dart=_Dart(), price_provider=_Price())
    assert isinstance(pipe.adapter, KrAdapter)
    assert pipe.adapter.corp_code_for_stock("000050") == "corp:000050"
