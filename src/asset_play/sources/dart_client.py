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
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from ..config import Config
from ..domain.enums import FSType, Market, MeasurementModel
from ..domain.models import Company, EquityHolding
from ..domain.units import MoneyUnit, to_decimal, to_won
from ..exceptions import ConfigError, QuotaExceededError, SourceError
from .base import HttpSource, QuotaTracker
from .dart_document import (
    InvestmentPropertyFairValue,
    LandHolding,
    parse_ip_pairs,
    parse_land_holdings,
    resolve_ip_fair_value,
)

BASE_URL = "https://opendart.fss.or.kr/api"

# 정기보고서 코드
REPORT_ANNUAL = "11011"  # 사업보고서
REPORT_HALF = "11012"  # 반기보고서
REPORT_Q1 = "11013"  # 1분기보고서
REPORT_Q3 = "11014"  # 3분기보고서

# DART status codes that mean "stop / config problem".
_KEY_ERRORS = {"010", "011", "012", "901"}

# 타법인출자현황 emits a 합계/소계 total row alongside real holdings; it must be dropped
# or it pollutes book-value aggregates and item counts.
_SUMMARY_ROW_NAMES = {"합계", "소계", "계", "총계"}


def _is_summary_row(name: Optional[str]) -> bool:
    return re.sub(r"\s+", "", name or "") in _SUMMARY_ROW_NAMES


# Name-matching alias DB lives in data, not code (see data/name_aliases.json). 타법인출자현황
# gives investee names only (no code), and the corpCode master writes conglomerates in Latin
# (LG전자) while reports spell them in Hangul (엘지전자) — so we transliterate a leading Hangul
# short form to its Latin master form. The map is editable data; users extend it without code
# changes (and via a merged user file pointed at by ASSET_PLAY_NAME_ALIASES).
_ALIASES_PATH = Path(__file__).resolve().parent.parent / "data" / "name_aliases.json"


def _read_aliases(path) -> tuple[dict[str, str], dict[str, str]]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    trans = {str(k): str(v) for k, v in (raw.get("transliterations") or {}).items()}
    names = {str(k): str(v) for k, v in (raw.get("names") or {}).items()}
    return trans, names


def load_name_aliases(extra_path=None) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(transliterations, names)`` = packaged defaults merged with an optional
    user file (user entries win). ``transliterations``: leading Hangul short form → Latin.
    ``names``: full investee name → stock_code override."""
    trans, names = _read_aliases(_ALIASES_PATH)
    if extra_path:
        u_trans, u_names = _read_aliases(extra_path)
        trans = {**trans, **u_trans}
        names = {**names, **u_names}
    return trans, names


_DEFAULT_TRANSLIT, _DEFAULT_NAMES = load_name_aliases()
_DEFAULT_TRANSLIT_KEYS = sorted(_DEFAULT_TRANSLIT, key=len, reverse=True)

_PAREN_RE = re.compile(r"\([^()]*\)|（[^（）]*）")  # footnotes / (주) / (*1)
_FOOTNOTE_RE = re.compile(r"\*\s*\d+\s*\)?")  # bare star-footnotes: *1) *5 (no opening paren)
_CORP_FORM_RE = re.compile(r"주식회사|㈜|유한회사|유한책임회사|합자회사|합명회사")
_NONNAME_RE = re.compile(r"[\s.,'\"&\-_/()*·ㆍ・]+")


def normalize_corp_name(name: Optional[str], translit: Optional[dict[str, str]] = None) -> str:
    """Canonicalize a Korean corporate name for cross-source matching.

    Drops parenthetical footnotes/affixes ((*2), (주)), bare star-footnotes (*1)), corporate-
    form tokens (주식회사/㈜/유한회사), strips whitespace+punctuation, upper-cases, then
    transliterates a leading Hangul conglomerate short form to its Latin master form using
    ``translit`` (defaults to the packaged alias DB). Returns "" for empty input.
    """
    if not name:
        return ""
    s = _PAREN_RE.sub("", str(name))
    s = _FOOTNOTE_RE.sub("", s)
    s = _CORP_FORM_RE.sub("", s)
    s = _NONNAME_RE.sub("", s)
    s = s.upper()
    if translit is None:
        table, keys = _DEFAULT_TRANSLIT, _DEFAULT_TRANSLIT_KEYS
    else:
        table, keys = translit, sorted(translit, key=len, reverse=True)
    for hangul in keys:
        if s.startswith(hangul):
            return table[hangul] + s[len(hangul):]
    return s


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
    sj_div: Optional[str] = None,
) -> Optional[Decimal]:
    """Pull an amount (in 원) for the first matching ``account_nm`` from fnlttSinglAcntAll rows.

    Pass ``sj_div`` (e.g. "BS") to restrict to one statement — names like 자본총계 and
    지배기업소유주지분 recur across BS/SCE/CIS, so the statement filter avoids false matches.
    """
    targets = {n.replace(" ", "") for n in account_names}
    for r in rows:
        if sj_div is not None and (r.get("sj_div") or "") != sj_div:
            continue
        nm = (r.get("account_nm") or "").replace(" ", "")
        if nm in targets:
            return to_won(r.get(field), unit)
    return None


def _ipfv_to_cache(r: InvestmentPropertyFairValue) -> dict:
    def s(v):
        return None if v is None else str(v)

    return {
        "ip_book": s(r.ip_book), "ip_fair": s(r.ip_fair),
        "land_book": s(r.land_book), "land_fair": s(r.land_fair),
        "unit_multiplier": r.unit_multiplier, "reconciled": r.reconciled, "basis": r.basis,
    }


def _ipfv_from_cache(d: dict) -> InvestmentPropertyFairValue:
    def dec(v):
        return None if v is None else Decimal(v)

    return InvestmentPropertyFairValue(
        ip_book=Decimal(d["ip_book"]), ip_fair=Decimal(d["ip_fair"]),
        land_book=dec(d.get("land_book")), land_fair=dec(d.get("land_fair")),
        unit_multiplier=int(d["unit_multiplier"]), reconciled=bool(d["reconciled"]),
        basis=d.get("basis", "OFS"),
    )


class DartClient(HttpSource):
    source_name = "DART"
    CORPCODE_NS = "dart:corpcode"

    def __init__(self, config: Optional[Config] = None, **kwargs: Any) -> None:
        config = config or Config()
        if kwargs.get("quota") is None:
            kwargs["quota"] = QuotaTracker(config.dart_daily_quota)
        super().__init__(config, **kwargs)
        self._stock_to_corp: Optional[dict[str, str]] = None
        self._name_to_stock: Optional[dict[str, str]] = None
        self._name_to_corp: Optional[dict[str, str]] = None
        # normalized-name indexes (fallback when exact name match fails)
        self._name_to_stock_norm: Optional[dict[str, str]] = None
        self._name_to_corp_norm: Optional[dict[str, str]] = None
        # name-matching alias DB (data-driven; user file merged via config.name_aliases_path)
        trans, names = load_name_aliases(getattr(config, "name_aliases_path", None))
        self._translit: Optional[dict[str, str]] = None if trans == _DEFAULT_TRANSLIT else trans
        self._alias_names: dict[str, str] = names

    def _normalize(self, name: Optional[str]) -> str:
        return normalize_corp_name(name, self._translit)

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
            self.cache.set_json(
                self.CORPCODE_NS, "name_to_stock_norm", self._name_to_stock_norm, ttl=self.config.cache_ttl_seconds
            )
            self.cache.set_json(
                self.CORPCODE_NS, "name_to_corp_norm", self._name_to_corp_norm, ttl=self.config.cache_ttl_seconds
            )
        return rows

    def _index(self, rows: list[dict[str, Optional[str]]]) -> None:
        self._stock_to_corp = {r["stock_code"]: r["corp_code"] for r in rows if r["stock_code"]}
        # name maps: first occurrence wins (names are not guaranteed unique).
        self._name_to_stock = {}
        self._name_to_corp = {}
        self._name_to_stock_norm = {}
        self._name_to_corp_norm = {}
        for r in rows:
            name = r["corp_name"]
            if not name:
                continue
            if name not in self._name_to_corp:
                self._name_to_corp[name] = r["corp_code"]
            if r["stock_code"] and name not in self._name_to_stock:
                self._name_to_stock[name] = r["stock_code"]
            nkey = self._normalize(name)
            if nkey and nkey not in self._name_to_corp_norm:
                self._name_to_corp_norm[nkey] = r["corp_code"]
            if nkey and r["stock_code"] and nkey not in self._name_to_stock_norm:
                self._name_to_stock_norm[nkey] = r["stock_code"]
        # alias DB explicit name→stock overrides take precedence over the corpCode heuristic
        for raw_name, code in self._alias_names.items():
            nkey = self._normalize(raw_name)
            if nkey:
                self._name_to_stock_norm[nkey] = code

    def _ensure_index(self, key: str) -> Optional[dict]:
        attr = {
            "stock_to_corp": "_stock_to_corp",
            "name_to_stock": "_name_to_stock",
            "name_to_corp": "_name_to_corp",
            "name_to_stock_norm": "_name_to_stock_norm",
            "name_to_corp_norm": "_name_to_corp_norm",
        }[key]
        current = getattr(self, attr)
        if current is None and self.cache is not None:
            current = self.cache.get_json(self.CORPCODE_NS, key)
            if current is None:
                # Older caches predate the normalized indexes — rebuild in-memory from
                # the cached full table so resolution still works without a re-sync.
                allrows = self.cache.get_json(self.CORPCODE_NS, "all")
                if allrows:
                    self._index(allrows)
                    current = getattr(self, attr)
            else:
                setattr(self, attr, current)
        return current

    def stock_code_for_name(self, name: str) -> Optional[str]:
        exact = self._ensure_index("name_to_stock")
        hit = exact.get((name or "").strip()) if exact else None
        if hit:
            return hit
        norm = self._ensure_index("name_to_stock_norm")
        return norm.get(self._normalize(name)) if norm else None

    def corp_code_for_name(self, name: str) -> Optional[str]:
        exact = self._ensure_index("name_to_corp")
        hit = exact.get((name or "").strip()) if exact else None
        if hit:
            return hit
        norm = self._ensure_index("name_to_corp_norm")
        return norm.get(self._normalize(name)) if norm else None

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
        est = (data.get("est_dt") or "").strip()
        year = int(est[:4]) if est[:4].isdigit() else None
        return Company(
            corp_code=corp_code,
            stock_code=stock or None,
            name=data.get("corp_name") or data.get("stock_name") or corp_code,
            market=Market.from_dart_corp_cls(data.get("corp_cls")),
            establishment_year=year,
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
            self._parse_holding(row, corp_code, amount_unit)
            for row in data.get("list", [])
            if not _is_summary_row(row.get("inv_prm"))
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
            investment_purpose=(row.get("invstmnt_purps") or "").strip() or None,
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

    def _latest_annual_rcept(self, corp_code: str, bsns_year: str) -> Optional[str]:
        """사업연도 ``bsns_year``의 사업보고서 rcept_no (정정 시 최신). FY는 익년 Q1에 제출."""
        y = int(bsns_year)
        disc = self.get_disclosures(corp_code, f"{y + 1}0101", f"{y + 1}1231")
        annual = [d for d in disc if "사업보고서" in (d.get("report_nm") or "")]
        # FY 정확 표기 "(YYYY.12)" 우선 (반기/분기 정정과 혼동 방지)
        exact = [d for d in annual if f"({bsns_year}.12)" in (d.get("report_nm") or "")]
        cands = exact or annual
        if not cands:
            return None
        cands.sort(key=lambda d: d.get("rcept_dt") or "", reverse=True)  # 최신 정정 우선
        return cands[0].get("rcept_no")

    def get_document_xml(self, rcept_no: str) -> Optional[str]:
        """사업보고서 본문 document.xml (ZIP → 최대 멤버 XML, 디코딩). 실패 시 None."""
        raw = self.get_bytes(
            f"{BASE_URL}/document.xml",
            params={"crtfc_key": self._key(), "rcept_no": rcept_no},
        )
        if not raw:
            return None
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            return None
        names = zf.namelist()
        if not names:
            return None
        data = zf.read(max(names, key=lambda n: zf.getinfo(n).file_size))
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    def get_investment_property_fair_value(
        self, corp_code: str, bsns_year: str, reprt_code: str = REPORT_ANNUAL
    ) -> Optional[InvestmentPropertyFairValue]:
        """별도(OFS) 투자부동산 토지/건물 장부·공정가치 (원). 단위는 BS 대사로 자동검출.

        공정가치 주석이 없거나(None) 단위 대사 실패 시 ``reconciled=False`` — 자동주입 금지
        (SPEC-IPNOTE-001 AC-2/5). document.xml은 크므로 파싱 결과를 캐시한다.
        """
        ck = f"{corp_code}:{bsns_year}:{reprt_code}"
        ns = "dart:ipfv2"  # v2 schema (ip_book/ip_fair); bump invalidates old-format entries
        if self.cache is not None:
            cached = self.cache.get_json(ns, ck)
            if cached is not None:
                return None if cached.get("none") else _ipfv_from_cache(cached)

        result = self._compute_ipfv(corp_code, bsns_year, reprt_code)
        if self.cache is not None:
            self.cache.set_json(
                ns, ck,
                {"none": True} if result is None else _ipfv_to_cache(result),
            )
        return result

    def _compute_ipfv(
        self, corp_code: str, bsns_year: str, reprt_code: str
    ) -> Optional[InvestmentPropertyFairValue]:
        rcept = self._latest_annual_rcept(corp_code, bsns_year)
        if not rcept:
            return None
        text = self.get_document_xml(rcept)
        if not text:
            return None
        pairs = parse_ip_pairs(text)
        if not pairs["OFS"] and not pairs["CFS"]:  # 투자부동산 공정가치 주석 부재 → 정상 None
            return None
        rows = self.get_financial_statements(corp_code, bsns_year, reprt_code, fs_div="OFS")
        bs_ip = extract_account_amount(rows, ["투자부동산"], sj_div="BS") if rows else None
        return resolve_ip_fair_value(pairs, bs_ip)  # 대사 실패 시 None (자동주입 금지)

    def get_land_holdings(self, corp_code: str, bsns_year: str) -> list:
        """사업보고서 '생산설비>토지' 표의 사업장별 소재지(주소)+장부가 — 위치 표시용(NAV 비반영).

        document.xml은 크므로 소재지/장부가만 캐시한다. 표가 없으면 [].
        """
        ns, ck = "dart:landhold", f"{corp_code}:{bsns_year}"
        if self.cache is not None:
            cached = self.cache.get_json(ns, ck)
            if cached is not None:
                return [
                    LandHolding(h["office"], h["location"], Decimal(h["book_value"]))
                    for h in cached
                ]
        rcept = self._latest_annual_rcept(corp_code, bsns_year)
        text = self.get_document_xml(rcept) if rcept else None
        holdings = parse_land_holdings(text) if text else []
        if self.cache is not None:
            self.cache.set_json(ns, ck, [
                {"office": h.office, "location": h.location, "book_value": str(h.book_value)}
                for h in holdings
            ])
        return holdings

    def get_net_assets(
        self, corp_code: str, bsns_year: str, reprt_code: str = REPORT_ANNUAL
    ) -> Optional[Decimal]:
        """순자산(자본총계), 원 — used for unlisted approximation (SPEC-UNLISTED-001)."""
        rows = self.get_financial_statements(corp_code, bsns_year, reprt_code)
        if not rows:
            return None
        return extract_account_amount(rows, ["자본총계", "자본 총계"])

    def get_separate_total_equity(
        self, corp_code: str, bsns_year: str, reprt_code: str = REPORT_ANNUAL
    ) -> Optional[Decimal]:
        """별도(OFS) 자본총계 (BS), 원 — reported_book_equity for revalued NAV (SPEC-NAV rev.3).

        OFS basis matches the 별도 cost-basis used for holdings surplus; consolidated
        controlling-interest equity would double-count subsidiary retained earnings.
        """
        rows = self.get_financial_statements(corp_code, bsns_year, reprt_code, fs_div="OFS")
        if not rows:
            return None
        return extract_account_amount(rows, ["자본총계", "자본 총계"], sj_div="BS")

    def get_screen_financials(
        self, corp_code: str, bsns_year: str, reprt_code: str = REPORT_ANNUAL
    ) -> tuple:
        """(지배주주지분, 자본총계, 자산총계, 당기순이익) — 연결(CFS), 1차 스크린용 (SPEC-SCREEN-001).

        증권앱 PBR/자기자본비율 정의(연결)와 정합. 지배주주지분이 없으면(별도 보고) 자본총계로 대체.
        """
        rows = self.get_financial_statements(corp_code, bsns_year, reprt_code, fs_div="CFS")
        if not rows:
            return (None, None, None, None)
        eq_total = extract_account_amount(rows, ["자본총계", "자본 총계"], sj_div="BS")
        eq_ctrl = extract_account_amount(
            rows, ["지배기업 소유주지분", "지배기업소유주지분", "지배기업의 소유주에게 귀속되는 자본"], sj_div="BS"
        )
        assets = extract_account_amount(rows, ["자산총계", "자산 총계"], sj_div="BS")
        net_income = extract_account_amount(
            rows, ["지배기업소유주지분순이익", "당기순이익(손실)", "당기순이익"], sj_div="IS"
        )
        return (eq_ctrl or eq_total, eq_total, assets, net_income)

    def get_disclosures(self, corp_code: str, bgn_de: str, end_de: str) -> list[dict]:
        """DART 공시 목록 (list.json), YYYYMMDD 범위 — 카탈리스트 신호용 (SPEC-CATALYST-001)."""
        data = self.get_json(
            f"{BASE_URL}/list.json",
            params={
                "crtfc_key": self._key(),
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "page_count": "100",
            },
            namespace="dart:list",
            cache_key=f"{corp_code}:{bgn_de}:{end_de}",
        )
        if not self._check_status(data):
            return []
        return data.get("list", [])
