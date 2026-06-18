"""Multi-market seam (SPEC-ADAPTER-001).

The valuation/screen/report core is market-agnostic — it depends only on data, not on a
specific market's APIs. A :class:`MarketAdapter` exposes that data surface; :class:`KrAdapter`
wraps the Korean stack (DART filings + KRX prices) as a pure delegate. New markets
(JP EDINET, US EDGAR) add an adapter without touching the core.

US note: markets that do not disclose investment-property fair value (US GAAP) return None
from ``get_investment_property_fair_value`` — NAV then uses screen + listed holdings only
(no fabrication).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional, Protocol, runtime_checkable

from ..domain.models import Company


@runtime_checkable
class MarketAdapter(Protocol):
    """Per-market data surface consumed by the market-agnostic core (pipeline/screen/report)."""

    def corp_code_for_stock(self, stock_code: str) -> Optional[str]: ...

    def get_company(self, corp_code: str) -> Optional[Company]: ...

    def get_other_corp_investments(self, corp_code: str, bsns_year: str, reprt_code: str) -> list: ...

    def stock_code_for_name(self, name: str) -> Optional[str]: ...

    def corp_code_for_name(self, name: str) -> Optional[str]: ...

    def get_net_assets(self, corp_code: str, bsns_year: str, reprt_code: str) -> Optional[Decimal]: ...

    def get_separate_total_equity(
        self, corp_code: str, bsns_year: str, reprt_code: str
    ) -> Optional[Decimal]: ...

    def get_screen_financials(self, corp_code: str, bsns_year: str) -> tuple: ...

    def get_disclosures(self, corp_code: str, bgn_de: str, end_de: str) -> list: ...

    def get_investment_property_fair_value(self, corp_code: str, bsns_year: str): ...

    def get_market_cap(self, stock_code: str) -> Optional[Decimal]: ...

    def price_as_of(self) -> date: ...


class KrAdapter:
    """한국 어댑터 — DART(공시/재무/XBRL) + KRX(가격)를 멀티마켓 시임 뒤로 래핑.

    순수 델리게이트(로직 0): 기존 동작을 그대로 보존한다(SPEC-ADAPTER-001 AC-1).
    """

    def __init__(self, dart, price_provider) -> None:
        self.dart = dart
        self.price = price_provider

    # -- filings / identity (DART) --------------------------------------- #
    def corp_code_for_stock(self, stock_code: str) -> Optional[str]:
        return self.dart.corp_code_for_stock(stock_code)

    def get_company(self, corp_code: str) -> Optional[Company]:
        return self.dart.get_company(corp_code)

    def get_other_corp_investments(self, corp_code: str, bsns_year: str, reprt_code: str) -> list:
        return self.dart.get_other_corp_investments(corp_code, bsns_year, reprt_code)

    def stock_code_for_name(self, name: str) -> Optional[str]:
        return self.dart.stock_code_for_name(name)

    def corp_code_for_name(self, name: str) -> Optional[str]:
        return self.dart.corp_code_for_name(name)

    def get_net_assets(self, corp_code: str, bsns_year: str, reprt_code: str) -> Optional[Decimal]:
        return self.dart.get_net_assets(corp_code, bsns_year, reprt_code)

    def get_separate_total_equity(
        self, corp_code: str, bsns_year: str, reprt_code: str
    ) -> Optional[Decimal]:
        return self.dart.get_separate_total_equity(corp_code, bsns_year, reprt_code)

    def get_screen_financials(self, corp_code: str, bsns_year: str) -> tuple:
        return self.dart.get_screen_financials(corp_code, bsns_year)

    def get_disclosures(self, corp_code: str, bgn_de: str, end_de: str) -> list:
        return self.dart.get_disclosures(corp_code, bgn_de, end_de)

    def get_investment_property_fair_value(self, corp_code: str, bsns_year: str):
        return self.dart.get_investment_property_fair_value(corp_code, bsns_year)

    # -- pricing (KRX) --------------------------------------------------- #
    def get_market_cap(self, stock_code: str) -> Optional[Decimal]:
        return self.price.get_market_cap(stock_code)

    def price_as_of(self) -> date:
        return self.price.as_of()
