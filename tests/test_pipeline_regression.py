"""End-to-end holdco regression fixture (TRUST §5).

A synthetic holding company that owns two listed subsidiaries plus one unlisted affiliate,
exercising the whole pipeline (CORE → EQUITY → UNLISTED → NAV → report) with no network.
"""

from datetime import date
from decimal import Decimal

from asset_play.aggregate.nav import AssetClass
from asset_play.config import Config
from asset_play.domain.enums import Market
from asset_play.domain.models import Company, EquityHolding
from asset_play.pipeline import Pipeline
from asset_play.sources.krx import StaticPriceProvider

from .fakes import FakeDart


def _build_pipeline():
    holdco = Company(
        corp_code="0000HOLD", stock_code="000001", name="테스트지주", market=Market.KOSPI
    )
    holdings = [
        # listed subsidiary A — resolved by name; 1,000,000주 @50,000, book 100억
        EquityHolding(
            investee_name="상장자회사A", shares=Decimal("1000000"), book_value=Decimal("10000000000")
        ),
        # listed affiliate B — 100,000주 @80,000, book 50억
        EquityHolding(
            investee_name="상장관계사B", shares=Decimal("100000"), book_value=Decimal("5000000000")
        ),
        # unlisted affiliate C — 30%, book 20억, investee net assets 200억
        EquityHolding(
            investee_name="비상장C", ownership_ratio=Decimal("30"), book_value=Decimal("2000000000")
        ),
    ]
    dart = FakeDart(
        holdco,
        holdings,
        stock_to_corp={"000001": "0000HOLD"},
        name_to_stock={"상장자회사A": "000270", "상장관계사B": "005930"},
        name_to_corp={"비상장C": "0000UNLC"},
        net_assets_by_corp={"0000UNLC": Decimal("20000000000")},
    )
    provider = StaticPriceProvider(
        prices={"000270": Decimal("50000"), "005930": Decimal("80000")},
        market_caps={"000001": Decimal("100000000000")},  # holdco 시총 1000억
        as_of_date=date(2026, 6, 1),
        source_name="KRX",
    )
    return Pipeline(Config(), dart=dart, price_provider=provider)


def test_holdco_regression_full_pipeline():
    pipe = _build_pipeline()
    run = pipe.run(stock_codes=["000001"])

    assert len(run.results) == 1
    nav = run.results[0]
    assert nav.name == "테스트지주"
    assert nav.market_cap == Decimal("100000000000")

    equity = nav.by_class[AssetClass.EQUITY]
    unlisted = nav.by_class[AssetClass.UNLISTED_EQUITY]
    # A: 1,000,000×50,000 − 100억 = 400억 ; B: 100,000×80,000 − 50억 = 30억
    assert equity.unrealized_gain == Decimal("43000000000")
    assert equity.item_count == 2
    # C: 200억×30% − 20억 = 40억
    assert unlisted.unrealized_gain == Decimal("4000000000")

    # pretax = 470억 ; after-tax (22%) = 366.6억
    assert nav.total_unrealized_pretax == Decimal("47000000000")
    assert nav.net_surplus == Decimal("36660000000")
    # holdco discount: surplus_ratio = 366.6억 / 1000억 = 0.3666
    assert nav.surplus_ratio == Decimal("0.366600")
    # mixed precision: unlisted LOW drags overall confidence down (NAV AC-2)
    assert nav.overall_confidence.value == "低"


def test_report_generation_smoke(tmp_path):
    pipe = _build_pipeline()
    run, csv_path, html_path = pipe.run_and_report(out_dir=tmp_path, stock_codes=["000001"])
    assert csv_path.exists() and html_path.exists()
    assert run.results[0].surplus_ratio == Decimal("0.366600")


def test_unresolved_report_collected_and_ranked():
    pipe = _build_pipeline()
    run = pipe.run(stock_codes=["000001"])
    # 비상장C did not resolve to a listed stock code → surfaces in the unresolved report
    names = [name for name, *_ in run.unresolved]
    assert "비상장C" in names
    assert "상장자회사A" not in names  # resolved → not reported
    books = [book for _, book, _ in run.unresolved]
    assert books == sorted(books, reverse=True)  # ranked by book value desc


def test_rank_unresolved_dedupes_by_name_keeping_max_book():
    from asset_play.pipeline import _rank_unresolved

    ranked = _rank_unresolved(
        [("엘지전자", Decimal("100"), "A"), ("엘지전자", Decimal("300"), "B"), ("씨제이", Decimal("200"), "A")]
    )
    assert [(n, b) for n, b, _ in ranked] == [("엘지전자", Decimal("300")), ("씨제이", Decimal("200"))]
