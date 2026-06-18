"""Unit normalization — TRUST invariant #4: everything money is in **원 (KRW)**.

Korean filings mix 원/천원/백만원/억원 (often declared as "단위: 백만원" in a header),
and land areas mix ㎡ and 평. All conversions funnel through here so the rest of the
codebase only ever sees won (``Decimal``) and square metres (``Decimal``).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional, Union

Number = Union[int, float, str, Decimal, None]

# 1 평 (pyeong) = 400/121 ㎡ ≈ 3.305785124 ㎡ (exact legal definition).
PYEONG_TO_SQM = Decimal(400) / Decimal(121)


class MoneyUnit(str, Enum):
    """Multipliers to convert a declared amount into 원."""

    WON = "원"
    THOUSAND_WON = "천원"
    MILLION_WON = "백만원"
    HUNDRED_MILLION_WON = "억원"
    BILLION_WON = "십억원"


_MONEY_MULTIPLIER: dict[MoneyUnit, Decimal] = {
    MoneyUnit.WON: Decimal(1),
    MoneyUnit.THOUSAND_WON: Decimal(1_000),
    MoneyUnit.MILLION_WON: Decimal(1_000_000),
    MoneyUnit.HUNDRED_MILLION_WON: Decimal(100_000_000),
    MoneyUnit.BILLION_WON: Decimal(1_000_000_000),
}

# Order matters: match the longer/more-specific tokens first.
_UNIT_TOKENS: tuple[tuple[str, MoneyUnit], ...] = (
    ("십억원", MoneyUnit.BILLION_WON),
    ("십억", MoneyUnit.BILLION_WON),
    ("백만원", MoneyUnit.MILLION_WON),
    ("백만", MoneyUnit.MILLION_WON),
    ("억원", MoneyUnit.HUNDRED_MILLION_WON),
    ("억", MoneyUnit.HUNDRED_MILLION_WON),
    ("천원", MoneyUnit.THOUSAND_WON),
    ("천", MoneyUnit.THOUSAND_WON),
    ("원", MoneyUnit.WON),
)


def to_decimal(value: Number) -> Optional[Decimal]:
    """Parse a possibly-messy numeric value into ``Decimal`` (or ``None``).

    Handles thousands separators, full-width minus, parentheses-negatives, and the
    DART/KRX placeholders for "no value" (``-``, ``""``, ``"N/A"``).
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip()
    if text in ("", "-", "—", "N/A", "n/a", "해당사항없음", "해당없음"):
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace(",", "").replace("−", "-").replace(" ", "")
    if text.startswith("△") or text.startswith("▲"):  # Korean accounting negatives
        negative = True
        text = text[1:]

    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return -result if negative else result


def parse_money_unit(text: Optional[str], default: MoneyUnit = MoneyUnit.WON) -> MoneyUnit:
    """Extract a money unit from a header like ``"(단위: 백만원)"``."""
    if not text:
        return default
    cleaned = str(text)
    # Look for "단위" context first, else scan the whole string.
    m = re.search(r"단위\s*[:：]?\s*([가-힣]+)", cleaned)
    scan = m.group(1) if m else cleaned
    for token, unit in _UNIT_TOKENS:
        if token in scan:
            return unit
    return default


def to_won(amount: Number, unit: Union[MoneyUnit, str, None] = MoneyUnit.WON) -> Optional[Decimal]:
    """Normalize ``amount`` (declared in ``unit``) into 원."""
    dec = to_decimal(amount)
    if dec is None:
        return None
    if isinstance(unit, str) and not isinstance(unit, MoneyUnit):
        unit = parse_money_unit(unit)
    if unit is None:
        unit = MoneyUnit.WON
    return dec * _MONEY_MULTIPLIER[unit]


def round_won(amount: Optional[Decimal]) -> Optional[Decimal]:
    """Round to whole 원 (won has no subunit)."""
    if amount is None:
        return None
    return amount.quantize(Decimal(1))


def to_sqm(area: Number, unit: str = "㎡") -> Optional[Decimal]:
    """Normalize an area into square metres. ``unit`` may be ``㎡``/``m2``/``평``."""
    dec = to_decimal(area)
    if dec is None:
        return None
    u = (unit or "").strip().lower()
    if u in ("평", "py", "pyeong"):
        return dec * PYEONG_TO_SQM
    return dec  # ㎡ / m2 / m² and anything else treated as already-metric
