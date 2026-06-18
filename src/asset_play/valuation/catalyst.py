"""SPEC-CATALYST-001 v1 — 공시 신호 기반 카탈리스트 점수 + value-trap 필터.

한국 시장에서 숨은 가치가 '풀릴지'는 카탈리스트에 달려 있다. DART 공시검색(list.json)의
report_nm 키워드로 밸류업·자사주 소각/취득·배당 신호를 잡아 가중합 점수를 낸다. 신뢰성 있는
정량 신호(배당성향)·지배구조 신호는 v2로 보류(SPEC-CATALYST-001 한계 참조).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

_VALUE_UP = ("기업가치제고", "기업가치 제고")
_BUYBACK = ("주식소각", "자기주식취득", "자기주식 취득", "자기주식소각")
_DIVIDEND = ("현금ㆍ현물배당", "현금배당", "배당결정")

# nav_discount 가 이 값 이상이면서 실현가능 자산이 없고 카탈리스트도 없으면 value trap 경계.
VALUE_TRAP_DISCOUNT_THRESHOLD = Decimal("0.30")


@dataclass
class CatalystSignals:
    value_up: bool = False  # 기업가치제고계획(밸류업) 공시
    buyback_cancel: bool = False  # 자사주 소각·취득
    dividend: bool = False  # 현금배당 결정


def catalyst_signals(disclosures: list[dict]) -> CatalystSignals:
    """DART 공시목록(list.json)의 report_nm에서 카탈리스트 신호를 판정 (AC-1)."""
    names = [(d.get("report_nm") or "") for d in disclosures]

    def has(keywords: tuple) -> bool:
        return any(any(k in n for k in keywords) for n in names)

    return CatalystSignals(
        value_up=has(_VALUE_UP), buyback_cancel=has(_BUYBACK), dividend=has(_DIVIDEND)
    )


def catalyst_score(signals: CatalystSignals) -> Decimal:
    """가중합 [0, 1] (AC-2): 밸류업 0.40 + 자사주 0.35 + 배당 0.25."""
    return (
        Decimal("0.40") * int(signals.value_up)
        + Decimal("0.35") * int(signals.buyback_cancel)
        + Decimal("0.25") * int(signals.dividend)
    )


def is_value_trap(
    nav_discount: Optional[Decimal],
    realizable_surplus: Decimal,
    catalyst_score_value: Decimal,
    *,
    threshold: Decimal = VALUE_TRAP_DISCOUNT_THRESHOLD,
) -> bool:
    """高 nav_discount + 인식형 일색(realizable ≤ 0) + 무카탈리스트 → value trap 경계 (AC-3)."""
    if nav_discount is None:
        return False
    return nav_discount >= threshold and realizable_surplus <= 0 and catalyst_score_value == 0
