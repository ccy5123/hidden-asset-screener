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


# --- JpAdapter (SPEC-JP-001): EDINET 財務·賃貸등不動산 + J-Quants 가격 ------------- #
def _jp_csv():
    def row(eid, ctx, cons, val):
        return "\t".join(f'"{c}"' for c in [eid, "i", ctx, "-", cons, "-", "u", "円", val])

    tb = ("単위：百万円 賃貸等不動産連結貸借対照表計上額期首残高53,06152,474"
          "期末残高52,47453,789期末時価91,02891,753")
    return "\n".join([
        "header",
        f'"jpcrp_cor:NotesRealEstateForLeaseEtcConsolidatedFinancialStatementsTextBlock"'
        f'\t"i"\t"c"\t"-"\t"その他"\t"-"\t"u"\t"－"\t"{tb}"',
        row("jppfs_cor:Assets", "CurrentYearInstant", "連結", "820851000000"),
        row("jppfs_cor:NetAssets", "CurrentYearInstant", "連結", "293044000000"),
        row("jpcrp_cor:NonControllingInterests", "CurrentYearInstant", "連結", "8958000000"),
        row("jpcrp_cor:ProfitLossAttributableToOwnersOfParent", "CurrentYearDuration", "連結", "32155000000"),
        row("jpcrp_cor:TotalNumberOfIssuedSharesSummaryOfBusinessResults",
            "CurrentYearInstant_NonConsolidatedMember", "その他", "79360000"),
    ])


class _Edinet:
    config = None

    def find_yuho(self, stock_code, dates):
        return {"docID": "D1", "secCode": "90310", "filerName": "西日本鉄道株式会社",
                "docTypeCode": "120"}

    def get_document_text(self, doc_id):
        return _jp_csv()

    @staticmethod
    def chintai_textblock(csv_text):
        from asset_play.sources.jp_edinet import EdinetClient
        return EdinetClient.chintai_textblock(csv_text)


class _JQ:
    def get_latest_close(self, code):
        return Decimal("3000")


def test_jpadapter_screen_and_chintai_and_marketcap():
    from asset_play.sources.adapter import JpAdapter

    a = JpAdapter(_Edinet(), _JQ(), dates=["2026-06-18"])
    assert isinstance(a, MarketAdapter)
    cc = a.corp_code_for_stock("9031")
    assert cc == "D1"
    assert a.get_company(cc).name == "西日本鉄道株式会社"

    eq_ctrl, eq_total, assets, ni = a.get_screen_financials(cc, "2025")
    assert eq_ctrl == Decimal("284086000000")   # 純資産−非支配持分
    assert assets == Decimal("820851000000")
    assert ni == Decimal("32155000000")

    ip = a.get_investment_property_fair_value(cc, "2025")
    assert ip.ip_book == Decimal("53789000000")   # 当期 期末残高 (百万円→円)
    assert ip.ip_fair == Decimal("91753000000")   # 当期 期末時価
    assert ip.reconciled is True

    # 시총 = 발행주식 79,360,000 × 종가 3,000
    assert a.get_market_cap("9031") == Decimal("238080000000")

    assert a.get_other_corp_investments(cc, "2025", "x") == []
    assert a.get_disclosures(cc, "a", "b") == []
