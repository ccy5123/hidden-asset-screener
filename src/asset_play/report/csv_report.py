"""CSV ranking report. Confidence + evidence sources travel with every row (AC-2/AC-3)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Union

import pandas as pd

from ..aggregate.rank import rank_by_nav_discount
from ..domain.enums import AssetClass
from ..domain.models import NAVResult


def _class_gain(result: NAVResult, asset_class: AssetClass) -> Decimal:
    agg = result.by_class.get(asset_class)
    return agg.unrealized_gain if agg else Decimal(0)


def _row(rank: int, r: NAVResult) -> dict:
    sources = sorted({s.source for s in r.evidence})
    return {
        "rank": rank,
        "name": r.name,
        "stock_code": r.stock_code or "",
        "corp_code": r.corp_code,
        "market": r.market.value,
        "market_cap": r.market_cap,
        "reported_book_equity": r.reported_book_equity if r.reported_book_equity is not None else "",
        "revalued_nav": r.revalued_nav if r.revalued_nav is not None else "",
        "nav_discount": r.nav_discount if r.nav_discount is not None else "",
        "equity_gain": _class_gain(r, AssetClass.EQUITY),
        "land_gain": _class_gain(r, AssetClass.LAND),
        "investment_property_gain": _class_gain(r, AssetClass.INVESTMENT_PROPERTY),
        "unlisted_gain": _class_gain(r, AssetClass.UNLISTED_EQUITY),
        "realizable_surplus": r.realizable_surplus,
        "recognition_only_surplus": r.recognition_only_surplus,
        "total_unrealized_pretax": r.total_unrealized_pretax,
        "tax_rate": r.tax_rate,
        "total_unrealized_posttax": r.total_unrealized_posttax,
        "net_surplus": r.net_surplus,
        "surplus_ratio": r.surplus_ratio if r.surplus_ratio is not None else "",
        "confidence": r.overall_confidence.value if r.overall_confidence else "",
        "review_queue_count": r.review_queue_count,
        "evidence_sources": "; ".join(sources),
        "as_of": r.as_of_date.isoformat() if r.as_of_date else "",
        "warnings": " | ".join(r.warnings),
    }


def results_to_dataframe(results: list[NAVResult], *, rank: bool = True) -> pd.DataFrame:
    ordered = rank_by_nav_discount(results) if rank else list(results)
    return pd.DataFrame([_row(i + 1, r) for i, r in enumerate(ordered)])


def write_csv(results: list[NAVResult], path: Union[str, Path]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = results_to_dataframe(results)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # BOM for Excel/한글
    return path
