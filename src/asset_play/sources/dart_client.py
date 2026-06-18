"""DART OpenAPI client (SPEC-CORE-001).

Covers the four endpoints the screener needs:
- ``corpCode.xml``            — corp_code ↔ stock_code 매핑 (AC-1)
- ``company.json``            — 기업개황 (market from ``corp_cls``)
- ``otrCprInvstmntSttus.json``— 타법인출자현황 (별도 FS holdings; SPEC-EQUITY-001)
- ``fnlttSinglAcntAll.json``  — 단일회사 전체계정 재무제표 (fs_div=OFS → 별도)

The bundled parser uses ``requests`` directly (no hard dependency on OpenDartReader),
and every network path is injectable for tests.
"""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Any, Optional

from ..config import Config
from ..domain.enums import FSType, Market, MeasurementModel
from ..domain.models import Company, EquityHolding
from ..domain.units import MoneyUnit, to_decimal, to_won
from ..exceptions import ConfigError, QuotaExceededError, SourceError
from .base import HttpSource, QuotaTracker

BASE_URL = "https://opendart.fss.or.kr/api"

# 정기보고서 코드
REPORT_ANNUAL = "11011"  # 사업보고서
REPORT_HALF = "11012"  # 반기보고서
REPORT_Q1 = "11013"  # 1분기보고서
REPORT_Q3 = "11014"  # 3분기보고서

# DART status codes that mean "stop / config problem".
_KEY_ERRORS = {"010", "011", "012", "901"}


def classify_land_measurement_model(text: Optional[str]) -> MeasurementModel:
    """Classify land/PP&E measurement model from accounting-policy note text (CORE AC-3).

    Heuristic keyword match on 원가모형 / 재평가모형. When both appear (e.g. a policy-change
    note), the model attached to an *adoption* verb wins; ties fall back to last-mentioned.
    """
    if not text:
        return MeasurementModel.UNKNOWN
    t = re.sub(r"\s+", "", str(text))
    has_cost = "원가모형" in t
    has_reval = "재평가모형" in t

    if has_reval and not has_cost:
        return MeasurementModel.REVALUATION
    if has_cost and not has_reval:
        return MeasurementModel.COST
    if not has_cost and not has_reval:
        return MeasurementModel.UNKNOWN

    adopt = r"(으로|을채택|를채택|에따라|으로평가|으로측정|을적용|를적용|을사용|로측정)"
    reval_adopt = re.search(r"재평가모형" + adopt, t)
    cost_adopt = re.search(r"원가모형" + adopt, t)
    if reval_adopt and not cost_adopt:
        return MeasurementModel.REVALUATION
    if cost_adopt and not reval_adopt:
        return MeasurementModel.COST
    # Ambiguous (both adopted or neither): last mention wins.
    return (
        MeasurementModel.COST
        if t.rfind("원가모형") > t.rfind("재평가모형")
        else MeasurementModel.REVALUATION
    )


def extract_account_amount(
    rows: list[dict],
    account_names: list[str],
    *,
    field: str = "thstrm_amount",
    unit: MoneyUnit = MoneyUnit.WON,
) -> Optional[Decimal]:
    """Pull an amount (in 원) for the first matching ``account_nm`` from fnlttSinglAcntAll rows."""
    targets = {n.replace(" ", "") for n in account_names}
    for r in rows:
        nm = (r.get("account_nm") or "").replace(" ", "")
        if nm in targets:
            return to_won(r.get(field), unit)
    return None


class DartClient(HttpSource):
    CORPCODE_NS = "dart:corpcode"

    def __init__(self, config: Optional[Config] = None, **kwargs: Any) -> None:
        config = config or Config()
        if kwargs.get("quota") is None:
            kwargs["quota"] = QuotaTracker(config.dart_daily_quota)
        super().__init__(config, **kwargs)
        self._stock_to_corp: Optional[dict[str, str]] = None
        self._name_to_stock: Optional[dict[str, str]] = None
        self._name_to_corp: Optional[dict[str, str]] = None

    # -- helpers ---------------------------------------------------------- #
    def _key(self) -> str:
        if not self.config.dart_api_key:
            raise ConfigError("DART API key missing (set ASSET_PLAY_DART_API_KEY)")
        return self.config.dart_api_key

    def _check_status(self, payload: dict) -> bool:
        """Return True if data present, False if 'no data' (013), else raise."""
        status = str(payload.get("status", "000"))
        if status == "000":
            return True
        msg = payload.get("message", "")
        if status == "013":
            return False
        if status == "020":
            raise QuotaExceededError(f"DART daily quota exceeded: {msg}")
        if status in _KEY_ERRORS:
            raise ConfigError(f"DART key/access error {status}: {msg}")
        raise SourceError(f"DART error {status}: {msg}")

    # -- corpCode (AC-1) -------------------------------------------------- #
    @staticmethod
    def _parse_corp_code_zip(content: bytes) -> list[dict[str, Optional[str]]]:
        zf = zipfile.ZipFile(io.BytesIO(content))
        xml_name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
        root = ET.fromstring(zf.read(xml_name))
        rows: list[dict[str, Optional[str]]] = []
        for el in root.iter("list"):
            stock = (el.findtext("stock_code") or "").strip()
            rows.append(
                {
                    "corp_code": (el.findtext("corp_code") or "").strip(),
                    "corp_name": (el.findtext("corp_name") or "").strip(),
                    "stock_code": stock or None,
                }
            )
        return rows

    def sync_corp_codes(self) -> list[dict[str, Optional[str]]]:
        """Download & cache the full corp_code ↔ stock_code mapping (CORE AC-1)."""
        content = self.get_bytes(f"{BASE_URL}/corpCode.xml", params={"crtfc_key": self._key()})
        rows = self._parse_corp_code_zip(content)
        self._index(rows)
        if self.cache is not None:
            self.cache.set_json(self.CORPCODE_NS, "all", rows, ttl=self.config.cache_ttl_seconds)
            self.cache.set_json(
                self.CORPCODE_NS, "stock_to_corp", self._stock_to_corp, ttl=self.config.cache_ttl_seconds
            )
            self.cache.set_json(
                self.CORPCODE_NS, "name_to_stock", self._name_to_stock, ttl=self.config.cache_ttl_seconds
            )
            self.cache.set_json(
                self.CORPCODE_NS, "name_to_corp", self._name_to_corp, ttl=self.config.cache_ttl_seconds
            )
        return rows

    def _index(self, rows: list[dict[str, Optional[str]]]) -> None:
        self._stock_to_corp = {r["stock_code"]: r["corp_code"] for r in rows if r["stock_code"]}
        # name maps: first occurrence wins (names are not guaranteed unique).
        self._name_to_stock = {}
        self._name_to_corp = {}
        for r in rows:
            name = r["corp_name"]
            if name and name not in self._name_to_corp:
                self._name_to_corp[name] = r["corp_code"]
            if name and r["stock_code"] and name not in self._name_to_stock:
                self._name_to_stock[name] = r["stock_code"]

    def _ensure_index(self, key: str) -> Optional[dict]:
        attr = {
            "stock_to_corp": "_stock_to_corp",
            "name_to_stock": "_name_to_stock",
            "name_to_corp": "_name_to_corp",
        }[key]
        current = getattr(self, attr)
        if current is None and self.cache is not None:
            current = self.cache.get_json(self.CORPCODE_NS, key)
            setattr(self, attr, current)
        return current

    def stock_code_for_name(self, name: str) -> Optional[str]:
        mapping = self._ensure_index("name_to_stock")
        return mapping.get((name or "").strip()) if mapping else None

    def corp_code_for_name(self, name: str) -> Optional[str]:
        mapping = self._ensure_index("name_to_corp")
        return mapping.get((name or "").strip()) if mapping else None

    def corp_code_for_stock(self, stock_code: str) -> Optional[str]:
        mapping = self._ensure_index("stock_to_corp")
        if mapping is None:
            raise SourceError("corp codes not synced; call sync_corp_codes() first")
        return mapping.get(stock_code)

    def is_listed_corp(self, corp_code: str) -> bool:
        """Listed ⇔ the corp_code maps to a non-empty stock_code in the synced table."""
        mapping = self._ensure_index("stock_to_corp")
        if not mapping:
            return False
        return corp_code in set(mapping.values())

    # -- 기업개황 --------------------------------------------------------- #
    def get_company(self, corp_code: str) -> Optional[Company]:
        data = self.get_json(
            f"{BASE_URL}/company.json",
            params={"crtfc_key": self._key(), "corp_code": corp_code},
            namespace="dart:company",
            cache_key=corp_code,
        )
        if not self._check_status(data):
            return None
        stock = (data.get("stock_code") or "").strip()
        return Company(
            corp_code=corp_code,
            stock_code=stock or None,
            name=data.get("corp_name") or data.get("stock_name") or corp_code,
            market=Market.from_dart_corp_cls(data.get("corp_cls")),
        )

    # -- 타법인출자현황 (SPEC-EQUITY-001) --------------------------------- #
    def get_other_corp_investments(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = REPORT_ANNUAL,
        *,
        amount_unit: MoneyUnit = MoneyUnit.WON,
    ) -> list[EquityHolding]:
        data = self.get_json(
            f"{BASE_URL}/otrCprInvstmntSttus.json",
            params={
                "crtfc_key": self._key(),
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
            },
            namespace="dart:otr_invest",
            cache_key=f"{corp_code}:{bsns_year}:{reprt_code}",
        )
        if not self._check_status(data):
            return []
        return [
            self._parse_holding(row, corp_code, amount_unit) for row in data.get("list", [])
        ]

    @staticmethod
    def _parse_holding(row: dict, holder_corp_code: str, unit: MoneyUnit) -> EquityHolding:
        return EquityHolding(
            holder_corp_code=holder_corp_code,
            investee_name=(row.get("inv_prm") or "").strip() or "(미상)",
            shares=to_decimal(row.get("trmend_blce_qy")),
            ownership_ratio=to_decimal(row.get("trmend_blce_qota_rt")),
            book_value=to_won(row.get("trmend_blce_acntbk_amount"), unit) or Decimal(0),
            acquisition_cost=to_won(row.get("frst_acqs_amount"), unit),
            fs_type=FSType.SEPARATE,  # 타법인출자현황 is reported on a separate basis
            source="DART:otrCprInvstmntSttus",
        )

    # -- 재무제표 (별도 = OFS) -------------------------------------------- #
    def get_financial_statements(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = REPORT_ANNUAL,
        fs_div: str = "OFS",
    ) -> list[dict]:
        data = self.get_json(
            f"{BASE_URL}/fnlttSinglAcntAll.json",
            params={
                "crtfc_key": self._key(),
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "fs_div": fs_div,
            },
            namespace="dart:fs_all",
            cache_key=f"{corp_code}:{bsns_year}:{reprt_code}:{fs_div}",
        )
        if not self._check_status(data):
            return []
        return data.get("list", [])

    def get_net_assets(
        self, corp_code: str, bsns_year: str, reprt_code: str = REPORT_ANNUAL
    ) -> Optional[Decimal]:
        """순자산(자본총계), 원 — used for unlisted approximation (SPEC-UNLISTED-001)."""
        rows = self.get_financial_statements(corp_code, bsns_year, reprt_code)
        if not rows:
            return None
        return extract_account_amount(rows, ["자본총계", "자본 총계"])
