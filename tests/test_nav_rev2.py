"""SPEC-NAV-001 rev.3 — revalued_nav / nav_discount, pretax·posttax, OFS-basis equity."""

from decimal import Decimal

from asset_play.aggregate.nav import SimpleValuation, aggregate_nav
from asset_play.domain.enums import AssetClass
from asset_play.domain.models import Company


def _val(gain: Decimal, book: Decimal = Decimal("100"), asset_id: str = "a") -> SimpleValuation:
    return SimpleValuation(
        asset_class=AssetClass.EQUITY,
        asset_id=asset_id,
        book_value=book,
        market_value=book + gain,
        unrealized_gain=gain,
    )


def _company(market_cap: str = "400") -> Company:
    return Company(corp_code="C", name="X", market_cap=Decimal(market_cap))


def test_revalued_nav_and_discount():  # AC-1
    nav = aggregate_nav(
        _company("400"), [_val(Decimal("200"))],
        tax_rate=Decimal("0.22"), reported_book_equity=Decimal("500"),
    )
    assert nav.total_unrealized_pretax == Decimal("200")
    assert nav.total_unrealized_posttax == Decimal("156")  # 200 × 0.78
    assert nav.net_surplus == Decimal("156")  # alias of posttax
    assert nav.reported_book_equity == Decimal("500")
    assert nav.revalued_nav == Decimal("656")  # 500 + 156
    assert nav.nav_discount == (Decimal(1) - Decimal("400") / Decimal("656")).quantize(
        Decimal("0.000001")
    )
    assert nav.surplus_ratio == (Decimal("156") / Decimal("400")).quantize(Decimal("0.000001"))


def test_posttax_no_refund_on_loss():  # AC-2
    nav = aggregate_nav(
        _company("400"), [_val(Decimal("-200"))],
        tax_rate=Decimal("0.22"), reported_book_equity=Decimal("500"),
    )
    assert nav.total_unrealized_pretax == Decimal("-200")
    assert nav.total_unrealized_posttax == Decimal("-200")  # no tax refund on a loss
    assert nav.revalued_nav == Decimal("300")  # 500 − 200


def test_nav_discount_na_when_revalued_nav_nonpositive():  # AC-3
    nav = aggregate_nav(
        _company("400"), [_val(Decimal("-200"))],
        tax_rate=Decimal("0.22"), reported_book_equity=Decimal("100"),
    )
    assert nav.revalued_nav == Decimal("-100")
    assert nav.nav_discount is None  # no divide-by-(≤0)
    assert any("revalued_nav" in w for w in nav.warnings)


def test_nav_discount_none_without_book_equity():
    nav = aggregate_nav(_company("400"), [_val(Decimal("200"))], tax_rate=Decimal("0.22"))
    assert nav.reported_book_equity is None
    assert nav.revalued_nav is None
    assert nav.nav_discount is None
