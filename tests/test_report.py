"""SPEC-NAV-001 AC-3 — CSV/HTML output is generated and evidence is traceable."""

from datetime import date
from decimal import Decimal

import pandas as pd

from asset_play.aggregate.nav import SimpleValuation, aggregate_nav
from asset_play.domain.enums import AssetClass, ConfidenceGrade
from asset_play.domain.models import Company, ValuationSnapshot
from asset_play.report import render_html, write_csv, write_html


def _results():
    company = Company(corp_code="0001", stock_code="000001", name="지주", market_cap=Decimal("100000000000"))
    vals = [
        SimpleValuation(
            asset_class=AssetClass.EQUITY,
            asset_id="eq1",
            book_value=Decimal("10000000000"),
            market_value=Decimal("50000000000"),
            unrealized_gain=Decimal("40000000000"),
            confidence=ConfidenceGrade.HIGH,
            snapshot=ValuationSnapshot(
                source="KRX:close", as_of_date=date(2026, 6, 1), method="shares × close"
            ),
        )
    ]
    return [aggregate_nav(company, vals, tax_rate=Decimal("0.22"))]


def test_write_csv_has_ranking_and_evidence(tmp_path):
    path = write_csv(_results(), tmp_path / "rank.csv")
    df = pd.read_csv(path)
    assert {"rank", "name", "net_surplus", "surplus_ratio", "confidence", "evidence_sources"} <= set(
        df.columns
    )
    assert df.iloc[0]["name"] == "지주"
    assert "KRX:close" in df.iloc[0]["evidence_sources"]
    assert df.iloc[0]["confidence"] == "高"


def test_render_html_contains_evidence_and_assumptions():
    html = render_html(_results())
    assert "지주" in html
    assert "KRX:close" in html
    assert "tax_rate" in html  # assumptions surfaced (traceable)
    assert "含み資産" in html


def test_write_html_file(tmp_path):
    path = write_html(_results(), tmp_path / "rank.html")
    assert path.exists()
    assert "<table" in path.read_text(encoding="utf-8")
