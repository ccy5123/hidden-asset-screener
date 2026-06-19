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

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, Protocol, runtime_checkable

from ..domain.enums import Market
from ..domain.models import Company


@dataclass
class MarketLabels:
    """시장별 리포트 표기(통화·출처·지표명·각주). 코어 로직은 불변, 라벨만 시장 인지."""

    currency: str         # 통화 표기 (예: "원(₩)" / "엔(¥)")
    source: str           # 출처명 (예: "DART 사업보고서" / "EDINET 有価証券報告書")
    asof_label: str       # 시세 출처 (예: "KRX 종가" / "J-Quants 종가")
    equity_label: str     # NAV 기준자본 라벨 (예: "별도(OFS) 자본총계" / "連結 지배지분")
    ip_label: str         # 투자부동산/含み益 라인 라벨
    footnotes: list = field(default_factory=list)


_KR_LABELS = MarketLabels(
    currency="원(₩)", source="DART 사업보고서", asof_label="KRX 종가",
    equity_label="별도(OFS) 자본총계", ip_label="투자부동산(공정가치 주석)",
    footnotes=[
        "장부·자본총계 = 별도(OFS) 기준. 시세 = 현재 KRX 종가.",
        "상장지분 range: S0 보수=장부 계상액(취득시점), S1·S2=현재 시가 (2시점).",
        "토지 range: S0=취득원가(장부), S1=공시지가×면적, S2=시가보정. 🔴 검토대기 필지는 S2 상한에만 가산(불확실).",
        "비상장은 순자산×지분율 근사, 시장가 아님.",
    ],
)
_JP_LABELS = MarketLabels(
    currency="엔(¥)", source="EDINET 有価証券報告書", asof_label="J-Quants 종가",
    equity_label="連結 지배지분(純資産−非支配)", ip_label="賃貸等不動産(時価 주석)",
    footnotes=[
        "재무·자본 = 連結(지배지분) 기준. 시세 = J-Quants 일봉 종가 × 발행주식수.",
        "賃貸등不動산 range: S0 보수=連結B/S 計上額(帳簿), S1·S2=会社 公示 期末時価.",
        "賃貸등不動산은 순수 임대분 + 사용겸용분 합산(사용겸용은 영업용 포함 — 보수적으로 時価 그대로).",
        "JP v1: 타법인출자 지분평가·카탈리스트 미지원(EDINET 持株 공시로 후속).",
    ],
)


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

    labels = _KR_LABELS

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

    def get_land_holdings(self, corp_code: str, bsns_year: str) -> list:
        return self.dart.get_land_holdings(corp_code, bsns_year)

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

    labels = _JP_LABELS

    def __init__(self, edinet, jquants, *, dates: Optional[list] = None,
                 landprice_index=None, geocoder=None) -> None:
        from .jp_edinet import recent_business_dates

        self.edinet = edinet
        self.jquants = jquants
        # 有報는 연 1회(결산월+3개월) 제출 → 어느 결산월 회사든 잡으려면 ~1년 창. find_yuho는
        # 최신순으로 훑다 첫 매칭에서 멈추므로, 최근 제출사는 그대로 빠르다(창 크기 무관).
        self.dates = dates or recent_business_dates(300)
        self.landprice_index = landprice_index  # JpLandPriceIndex (영업용 토지 추정용; None이면 미사용)
        self.geocoder = geocoder  # GsiGeocoder (좌표 최근접 #3; None이면 市区町村 median)
        self._meta: dict = {}   # stock_code → 有報 메타(dict) | None
        self._csv: dict = {}    # docID → CSV 텍스트
        self._fin: dict = {}    # docID → parse_jp_financials 결과
        self._html: dict = {}   # docID → 본문 HTML
        self._opland: dict = {}  # docID → OperatingLandEstimate 리스트

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

    def operating_land(self, corp_code: str) -> list:
        """영업용(자사전용) 토지 含み益 추정 (SPEC-JP-002) — 設備현황 파싱 + 公示地価 인덱스.

        賃貸등不動산(時価 공시분)은 파서가 제외(중복가드). landprice_index 없으면 빈 리스트.
        """
        if self.landprice_index is None:
            return []
        if corp_code in self._opland:
            return self._opland[corp_code]
        from .jp_edinet_document import parse_facilities_html
        from .jp_landprice import estimate_operating_land

        if corp_code not in self._html:
            self._html[corp_code] = self.edinet.get_document_html(corp_code) or ""
        facs = parse_facilities_html(self._html[corp_code])
        items = [(f["location"], f["area"], f["book_yen"], f["category"]) for f in facs]
        self._opland[corp_code] = estimate_operating_land(
            items, self.landprice_index, geocoder=self.geocoder)
        return self._opland[corp_code]

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
