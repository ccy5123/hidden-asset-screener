"""SPEC-CATALYST-001 v1 — 공시 신호 → catalyst_score → value-trap."""

from decimal import Decimal

from asset_play.valuation.catalyst import (
    CatalystSignals,
    catalyst_score,
    catalyst_signals,
    is_value_trap,
)


def test_catalyst_signals_from_report_names():  # AC-1
    disc = [
        {"report_nm": "기업가치제고계획(자율공시)"},
        {"report_nm": "주식소각결정"},
        {"report_nm": "현금ㆍ현물배당결정"},
        {"report_nm": "분기보고서"},
    ]
    s = catalyst_signals(disc)
    assert s.value_up and s.buyback_cancel and s.dividend


def test_catalyst_signals_partial():
    s = catalyst_signals([{"report_nm": "주요사항보고서(자기주식취득신탁계약체결결정)"}])
    assert s.buyback_cancel and not s.value_up and not s.dividend


def test_catalyst_score_weighted():  # AC-2
    assert catalyst_score(CatalystSignals(True, True, True)) == Decimal("1.00")
    assert catalyst_score(CatalystSignals(value_up=True)) == Decimal("0.40")
    assert catalyst_score(CatalystSignals()) == Decimal("0")


def test_value_trap_flag():  # AC-3
    assert is_value_trap(Decimal("0.4"), Decimal("0"), Decimal("0")) is True  # 高할인+인식형+무카탈
    assert is_value_trap(Decimal("0.4"), Decimal("0"), Decimal("0.4")) is False  # 카탈리스트 有
    assert is_value_trap(Decimal("0.4"), Decimal("100"), Decimal("0")) is False  # realizable 有
    assert is_value_trap(Decimal("0.1"), Decimal("0"), Decimal("0")) is False  # 할인 낮음
    assert is_value_trap(None, Decimal("0"), Decimal("0")) is False  # nav_discount N/A


def test_pipeline_catalyst_is_opt_in():  # AC-4
    from datetime import date

    from asset_play.cache import CacheStore
    from asset_play.config import Config
    from asset_play.domain.enums import Market
    from asset_play.domain.models import Company
    from asset_play.pipeline import Pipeline
    from asset_play.sources.krx import StaticPriceProvider

    from .fakes import FakeDart

    company = Company(corp_code="C", stock_code="000001", name="X", market=Market.KOSPI)
    dart = FakeDart(company, [], stock_to_corp={"000001": "C"},
                    separate_equity_by_corp={"C": Decimal("1000")})
    dart.disclosures = [{"report_nm": "기업가치제고계획(자율공시)"}, {"report_nm": "현금ㆍ현물배당결정"}]
    price = StaticPriceProvider(market_caps={"000001": Decimal("500")}, as_of_date=date(2026, 6, 1))
    pipe = Pipeline(Config(), dart=dart, price_provider=price, cache=CacheStore())

    base = pipe.run(stock_codes=["000001"], bsns_year="2024").results[0]
    assert base.catalyst_score is None  # 미사용 → 공시검색 안 함

    withc = pipe.run(stock_codes=["000001"], bsns_year="2024", compute_catalyst=True).results[0]
    assert withc.catalyst_score == Decimal("0.65")  # 밸류업 0.40 + 배당 0.25
