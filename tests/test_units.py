"""TRUST invariant #4 — unit normalization to 원 / ㎡."""

from decimal import Decimal

import pytest

from asset_play.domain.units import (
    MoneyUnit,
    PYEONG_TO_SQM,
    parse_money_unit,
    to_decimal,
    to_sqm,
    to_won,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234,567", Decimal("1234567")),
        ("(1,000)", Decimal("-1000")),
        ("△500", Decimal("-500")),
        ("-", None),
        ("", None),
        (None, None),
        (1500, Decimal("1500")),
    ],
)
def test_to_decimal(raw, expected):
    assert to_decimal(raw) == expected


def test_to_won_scales_by_unit():
    assert to_won("1,000", MoneyUnit.THOUSAND_WON) == Decimal("1000000")
    assert to_won(5, MoneyUnit.MILLION_WON) == Decimal("5000000")
    assert to_won(3, MoneyUnit.HUNDRED_MILLION_WON) == Decimal("300000000")
    assert to_won("12,345") == Decimal("12345")


def test_parse_money_unit_from_header():
    assert parse_money_unit("(단위: 백만원)") == MoneyUnit.MILLION_WON
    assert parse_money_unit("단위 : 천원") == MoneyUnit.THOUSAND_WON
    assert parse_money_unit(None) == MoneyUnit.WON


def test_to_sqm_pyeong_conversion():
    assert to_sqm(1, "평") == PYEONG_TO_SQM
    assert to_sqm("100", "㎡") == Decimal("100")
    assert to_sqm(None) is None
