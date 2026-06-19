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

from ..domain.enums import Market
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


class JpAdapter:
    """일본 어댑터 — EDINET(財務·賃貸등不動산) + J-Quants(주가). MarketAdapter 표면 (SPEC-JP-001).

    JP v1 범위: 1차 스크린(連結 財務) + 賃貸등不動산 含み益(한국 투자부동산 대응) + 시총.
    타법인출자 지분평가·카탈리스트는 미지원(빈값) — EDINET에 직접 대응이 없어 후속.
    corp_code = EDINET docID. 財務·賃貸등不動산은 같은 有報 CSV에서, 시총은 J-Quants 종가×발행주식수.
    """

    def __init__(self, edinet, jquants, *, dates: Optional[list] = None) -> None:
        from .jp_edinet import recent_business_dates

        self.edinet = edinet
        self.jquants = jquants
        self.dates = dates or recent_business_dates(40)
        self._meta: dict = {}   # stock_code → 有報 메타(dict) | None
        self._csv: dict = {}    # docID → CSV 텍스트
        self._fin: dict = {}    # docID → parse_jp_financials 결과

    def _yuho(self, stock_code: str) -> Optional[dict]:
        if stock_code not in self._meta:
            try:
                self._meta[stock_code] = self.edinet.find_yuho(stock_code, self.dates)
            except Exception:
                self._meta[stock_code] = None
        return self._meta[stock_code]

    def _csv_for(self, doc_id: str) -> str:
        if doc_id not in self._csv:
            self._csv[doc_id] = self.edinet.get_document_text(doc_id) or ""
        return self._csv[doc_id]

    def _financials(self, doc_id: str) -> dict:
        from .jp_edinet_document import parse_jp_financials

        if doc_id not in self._fin:
            self._fin[doc_id] = parse_jp_financials(self._csv_for(doc_id))
        return self._fin[doc_id]

    # -- MarketAdapter surface ------------------------------------------- #
    def corp_code_for_stock(self, stock_code: str) -> Optional[str]:
        m = self._yuho(stock_code)
        return m.get("docID") if m else None

    def get_company(self, corp_code: str) -> Optional[Company]:
        for m in self._meta.values():
            if m and m.get("docID") == corp_code:
                sec = m.get("secCode") or ""
                return Company(corp_code=corp_code, stock_code=(sec[:4] or None),
                               name=m.get("filerName") or corp_code, market=Market.OTHER)
        return None

    def get_screen_financials(self, corp_code: str, bsns_year: str) -> tuple:
        f = self._financials(corp_code)
        return (f["controlling_equity"], f["net_assets"], f["assets"], f["net_income"])

    def get_separate_total_equity(self, corp_code, bsns_year, reprt_code=None) -> Optional[Decimal]:
        # JP는 連結 지배지분을 revalued NAV 기준으로 사용(賃貸등不動산 時価도 連結 공시).
        return self._financials(corp_code)["controlling_equity"]

    def get_investment_property_fair_value(self, corp_code: str, bsns_year: str):
        from .dart_document import InvestmentPropertyFairValue
        from .jp_edinet_document import parse_chintai_fudosan

        items = parse_chintai_fudosan(self.edinet.chintai_textblock(self._csv_for(corp_code)))
        if not items:
            return None
        book = sum((it.book for it in items), Decimal(0))
        fair = sum((it.fair for it in items), Decimal(0))
        if fair <= 0:
            return None
        return InvestmentPropertyFairValue(
            ip_book=book, ip_fair=fair, land_book=None, land_fair=None,
            unit_multiplier=1, basis="連結", reconciled=True,
        )

    def get_market_cap(self, stock_code: str) -> Optional[Decimal]:
        m = self._yuho(stock_code)
        if not m:
            return None
        shares = self._financials(m["docID"]).get("shares")
        close = self.jquants.get_latest_close(stock_code) if self.jquants else None
        return shares * close if (shares is not None and close is not None) else None

    def price_as_of(self) -> date:
        return date.today()

    # JP v1 미지원(빈값) — 후속에서 EDINET 持株/공시로 확장
    def get_other_corp_investments(self, corp_code, bsns_year, reprt_code) -> list:
        return []

    def stock_code_for_name(self, name) -> Optional[str]:
        return None

    def corp_code_for_name(self, name) -> Optional[str]:
        return None

    def get_net_assets(self, corp_code, bsns_year, reprt_code) -> Optional[Decimal]:
        return None

    def get_disclosures(self, corp_code, bgn_de, end_de) -> list:
        return []
