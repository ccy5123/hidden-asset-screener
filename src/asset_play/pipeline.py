"""End-to-end orchestration.

    universe → [CORE 수집] → ├─ [EQUITY 정밀]  ─┐
                              ├─ [LAND 스크리닝/정밀] ┤→ [NAV 집계·랭킹] → 리포트
                              └─ [UNLISTED 근사] ─┘

Fully automated for Tier-1 (equity). Land precise valuation is opt-in (human-in-loop):
pass ``land_assets_by_corp`` plus a geocoder + land-price provider. Quota exhaustion is
caught per-company so partial results are preserved (CORE AC-4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Union

from .aggregate.nav import SimpleValuation, aggregate_nav, make_investment_property_item
from .aggregate.rank import rank_by_net_surplus
from .cache import CacheStore
from .config import Config
from .domain.enums import AssetClass
from .domain.models import Company, LandAsset, NAVResult
from .exceptions import QuotaExceededError, SourceError
from .report.csv_report import write_csv
from .report.html_report import write_html
from .sources.dart_client import REPORT_ANNUAL, DartClient
from .sources.krx import KrxClient, PriceProvider
from .sources.molit import LandPriceProvider
from .sources.vworld import Geocoder
from .valuation.equity import value_equity_holdings
from .valuation.land_precise import value_land_precise
from .valuation.land_screen import screen_land
from .valuation.unlisted import value_unlisted_holding


@dataclass
class PipelineRun:
    results: list[NAVResult] = field(default_factory=list)
    review_queue: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quota_exhausted: bool = False


class Pipeline:
    def __init__(
        self,
        config: Optional[Config] = None,
        *,
        dart: Optional[DartClient] = None,
        price_provider: Optional[PriceProvider] = None,
        geocoder: Optional[Geocoder] = None,
        land_price_provider: Optional[LandPriceProvider] = None,
        cache: Optional[CacheStore] = None,
    ) -> None:
        self.config = config or Config()
        self.cache = cache or CacheStore(str(self.config.cache_dir / "asset_play.sqlite"))
        self.dart = dart or DartClient(self.config, cache=self.cache)
        self.price_provider = price_provider or KrxClient(self.config, cache=self.cache)
        self.geocoder = geocoder
        self.land_price_provider = land_price_provider

    def sync_corp_codes(self):
        return self.dart.sync_corp_codes()

    def _resolve_targets(
        self, stock_codes: Optional[list[str]], corp_codes: Optional[list[str]]
    ) -> list[tuple[str, Optional[str]]]:
        targets: list[tuple[str, Optional[str]]] = []
        for sc in stock_codes or []:
            cc = self.dart.corp_code_for_stock(sc)
            if cc:
                targets.append((cc, sc))
        for cc in corp_codes or []:
            targets.append((cc, None))
        return targets

    def _company_for(self, corp_code: str, stock_code: Optional[str], as_of: date) -> Company:
        company = self.dart.get_company(corp_code) or Company(
            corp_code=corp_code, stock_code=stock_code, name=corp_code
        )
        if stock_code and not company.stock_code:
            company.stock_code = stock_code
        company.as_of_date = as_of
        if company.stock_code:
            company.market_cap = self.price_provider.get_market_cap(company.stock_code)
        return company

    def value_company(
        self,
        corp_code: str,
        stock_code: Optional[str],
        *,
        bsns_year: str,
        reprt_code: str = REPORT_ANNUAL,
        land_assets: Optional[list[LandAsset]] = None,
        as_of: Optional[date] = None,
    ) -> tuple[NAVResult, list]:
        as_of = as_of or self.price_provider.as_of()
        company = self._company_for(corp_code, stock_code, as_of)

        holdings = self.dart.get_other_corp_investments(corp_code, bsns_year, reprt_code)

        equity = value_equity_holdings(
            holdings,
            self.price_provider,
            resolve_stock_code=lambda h: self.dart.stock_code_for_name(h.investee_name),
            investee_market_cap=self.price_provider.get_market_cap,
            as_of=as_of,
        )

        valuations: list = list(equity.valuations)
        warnings: list[str] = list(equity.warnings)
        review_queue: list = []

        # Tier 3: unlisted holdings → net-asset approximation.
        for h in equity.tier3_queue:
            investee_cc = h.investee_corp_code or self.dart.corp_code_for_name(h.investee_name)
            net_assets = None
            if investee_cc:
                try:
                    net_assets = self.dart.get_net_assets(investee_cc, bsns_year, reprt_code)
                except SourceError:
                    net_assets = None
            valuations.append(value_unlisted_holding(h, net_assets=net_assets, as_of=as_of))

        # Tier 2: land (opt-in / human-in-loop).
        if land_assets:
            screen = screen_land(company, land_assets, as_of=as_of, config=self.config)
            if not screen.excluded:
                if screen.investment_property_fair_value:
                    valuations.append(
                        make_investment_property_item(
                            f"{corp_code}:ip",
                            sum(
                                (la.book_value for la in land_assets if la.fair_value is not None),
                                Decimal(0),
                            ),
                            screen.investment_property_fair_value,
                            snapshot=screen.snapshot,
                        )
                    )
                if self.geocoder and self.land_price_provider and screen.shortlisted:
                    precise = value_land_precise(
                        [la for la in land_assets if la.fair_value is None],
                        self.geocoder,
                        self.land_price_provider,
                        config=self.config,
                        as_of=as_of,
                    )
                    valuations.extend(precise.valuations)
                    review_queue.extend(precise.review_queue)
                    warnings.extend(precise.warnings)
            else:
                warnings.append(f"토지 제외: {screen.exclude_reason}")

        nav = aggregate_nav(
            company,
            valuations,
            tax_rate=self.config.corporate_tax_rate,
            correction_factor=self.config.land_price_correction_factor,
            review_queue_count=len(review_queue),
            as_of=as_of,
        )
        nav.warnings.extend(warnings)
        return nav, review_queue

    def run(
        self,
        stock_codes: Optional[list[str]] = None,
        corp_codes: Optional[list[str]] = None,
        *,
        bsns_year: Optional[str] = None,
        reprt_code: str = REPORT_ANNUAL,
        land_assets_by_corp: Optional[dict[str, list[LandAsset]]] = None,
        as_of: Optional[date] = None,
    ) -> PipelineRun:
        bsns_year = bsns_year or str(date.today().year - 1)
        land_assets_by_corp = land_assets_by_corp or {}
        run = PipelineRun()

        for corp_code, sc in self._resolve_targets(stock_codes, corp_codes):
            try:
                nav, review = self.value_company(
                    corp_code,
                    sc,
                    bsns_year=bsns_year,
                    reprt_code=reprt_code,
                    land_assets=land_assets_by_corp.get(corp_code),
                    as_of=as_of,
                )
            except QuotaExceededError as exc:  # AC-4: stop, preserve partial results
                run.quota_exhausted = True
                run.warnings.append(f"quota exhausted at {corp_code}: {exc}")
                break
            except SourceError as exc:
                run.warnings.append(f"skipped {corp_code}: {exc}")
                continue
            run.results.append(nav)
            run.review_queue.extend(review)

        run.results = rank_by_net_surplus(run.results)
        return run

    def run_and_report(
        self, *, out_dir: Union[str, Path] = "out", **kwargs
    ) -> tuple[PipelineRun, Path, Path]:
        run = self.run(**kwargs)
        out = Path(out_dir)
        csv_path = write_csv(run.results, out / "asset_play_ranking.csv")
        html_path = write_html(run.results, out / "asset_play_ranking.html")
        return run, csv_path, html_path
