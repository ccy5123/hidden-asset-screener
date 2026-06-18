"""SPEC-NAV-001 — AC-1..3 + dedup invariant #2."""

from datetime import date
from decimal import Decimal

from asset_play.aggregate.nav import SimpleValuation, aggregate_nav
from asset_play.domain.enums import AssetClass, ConfidenceGrade
from asset_play.domain.models import Company, ValuationSnapshot


def _company(market_cap=Decimal("100000000000")):
    return Company(corp_code="00000001", stock_code="000001", name="지주", market_cap=market_cap)


def _val(ac, aid, book, market, conf, src="KRX"):
    return SimpleValuation(
        asset_class=ac,
        asset_id=aid,
        book_value=Decimal(book),
        market_value=Decimal(market),
        unrealized_gain=Decimal(market) - Decimal(book),
        confidence=conf,
        snapshot=ValuationSnapshot(source=src, as_of_date=date(2026, 6, 1), method="m"),
    )


def test_ac1_pretax_aftertax_and_ratio():
    vals = [
        _val(AssetClass.EQUITY, "eq1", "10000000000", "50000000000", ConfidenceGrade.HIGH),
        _val(AssetClass.UNLISTED_EQUITY, "u1", "2000000000", "6000000000", ConfidenceGrade.LOW),
    ]
    nav = aggregate_nav(_company(), vals, tax_rate=Decimal("0.22"))
    # pretax = 40B + 4B = 44B; after-tax = 44B × 0.78 = 34.32B
    assert nav.total_unrealized_pretax == Decimal("44000000000")
    assert nav.net_surplus == Decimal("34320000000")
    assert nav.surplus_ratio == Decimal("0.343200")


def test_ac2_overall_confidence_is_weakest():
    vals = [
        _val(AssetClass.EQUITY, "eq1", "0", "100", ConfidenceGrade.HIGH),
        _val(AssetClass.LAND, "land1", "0", "100", ConfidenceGrade.MEDIUM),
        _val(AssetClass.UNLISTED_EQUITY, "u1", "0", "100", ConfidenceGrade.LOW),
    ]
    nav = aggregate_nav(_company(), vals)
    assert nav.overall_confidence == ConfidenceGrade.LOW


def test_invariant2_no_double_counting():
    vals = [
        _val(AssetClass.EQUITY, "dup", "0", "100", ConfidenceGrade.HIGH),
        _val(AssetClass.LAND, "dup", "0", "999", ConfidenceGrade.MEDIUM),  # same asset_id
    ]
    nav = aggregate_nav(_company(), vals)
    assert nav.total_unrealized_pretax == Decimal("100")  # second dropped
    assert any("이중계상" in w for w in nav.warnings)


def test_ac3_evidence_is_traceable():
    vals = [_val(AssetClass.EQUITY, "eq1", "0", "100", ConfidenceGrade.HIGH, src="KRX:close")]
    nav = aggregate_nav(_company(), vals)
    assert nav.evidence and nav.evidence[0].source == "KRX:close"
    assert nav.assumptions["tax_rate"] == "0.22"


def test_no_market_cap_yields_no_ratio():
    nav = aggregate_nav(
        _company(market_cap=None),
        [_val(AssetClass.EQUITY, "eq1", "0", "100", ConfidenceGrade.HIGH)],
    )
    assert nav.surplus_ratio is None
