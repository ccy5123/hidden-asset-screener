"""SPEC-JP-001 — EDINET(有報 XBRL) + J-Quants(주가) 라이브 클라이언트.

EdinetClient: 有報 목록/문서(type=5 CSV)·財務·賃貸등不動산 텍스트블록. Subscription-Key 쿼리인증.
JQuantsClient: V2 일봉 종가(x-api-key 헤더). 무료플랜은 주가만(財務는 EDINET).
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from ..exceptions import ConfigError
from .base import HttpSource

EDINET_BASE = "https://api.edinet-fsa.go.jp/api/v2"
JQUANTS_BASE = "https://api.jquants.com/v2"


def recent_business_dates(n: int = 40, end: Optional[date] = None) -> list:
    """``end``(기본 today)부터 과거 ``n`` 영업일(주말 제외) ISO 날짜 — 有報 스캔용."""
    if end is None:
        end = date.today()
    out: list = []
    d = end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out


class EdinetClient(HttpSource):
    source_name = "EDINET"

    def _key(self) -> str:
        if not self.config.edinet_key:
            raise ConfigError("EDINET key missing (set ASSET_PLAY_EDINET_KEY)")
        return self.config.edinet_key

    def list_documents(self, date_str: str) -> list:
        data = self.get_json(
            f"{EDINET_BASE}/documents.json",
            params={"date": date_str, "type": "2", "Subscription-Key": self._key()},
            namespace="edinet:list", cache_key=date_str,
        )
        return data.get("results", []) if isinstance(data, dict) else []

    def find_yuho(self, stock_code: str, dates: list) -> Optional[dict]:
        """주식코드(4자리)의 최신 有報(docTypeCode 120) 메타. ``dates``(최신순) 스캔."""
        sec5 = stock_code if len(stock_code) == 5 else f"{stock_code}0"
        for d in dates:
            for x in self.list_documents(d):
                if x.get("secCode") == sec5 and x.get("docTypeCode") == "120":
                    return x
        return None

    def get_document_text(self, doc_id: str) -> Optional[str]:
        """documents/{docID}?type=5 → ZIP → jpcrp 메인 CSV(UTF-16) 텍스트."""
        raw = self.get_bytes(
            f"{EDINET_BASE}/documents/{doc_id}",
            params={"type": "5", "Subscription-Key": self._key()},
        )
        if not raw:
            return None
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            return None
        main = [n for n in zf.namelist() if "jpcrp" in n and n.lower().endswith(".csv")]
        if not main:
            return None
        return zf.read(main[0]).decode("utf-16", errors="replace")

    def get_document_html(self, doc_id: str) -> Optional[str]:
        """documents/{docID}?type=1 → XBRL ZIP → 본문 iXBRL HTML(honbun). 設備현황 표 파싱용.

        type=5 CSV는 표를 평탄화해 셀 경계가 사라지므로, 셀 구조가 살아있는 type=1 사용.
        """
        raw = self.get_bytes(
            f"{EDINET_BASE}/documents/{doc_id}",
            params={"type": "1", "Subscription-Key": self._key()},
        )
        if not raw:
            return None
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            return None
        htmls = [n for n in zf.namelist()
                 if "honbun" in n.lower() and n.lower().endswith((".htm", ".html"))]
        if not htmls:
            return None
        return "".join(zf.read(n).decode("utf-8", errors="replace") for n in sorted(htmls))

    @staticmethod
    def chintai_textblock(csv_text: str) -> str:
        """賃貸等不動産 텍스트블록(HTML 제거) 추출. 없으면 빈 문자열."""
        for ln in (csv_text or "").splitlines():
            cols = [c.strip('"') for c in ln.split("\t")]
            if len(cols) >= 9 and "RealEstateForLease" in cols[0] and "TextBlock" in cols[0]:
                return re.sub(r"<[^>]+>", " ", cols[8])
        return ""


class JQuantsClient:
    """J-Quants V2 일봉 종가 (x-api-key). 무료플랜 주가용."""

    source_name = "J-Quants"

    def __init__(self, config, cache=None) -> None:
        self.config = config
        self.cache = cache

    def get_latest_close(self, stock_code: str) -> Optional[Decimal]:
        if not self.config.jquants_key:
            return None
        code5 = stock_code if len(stock_code) == 5 else f"{stock_code}0"
        import requests

        try:
            r = requests.get(
                f"{JQUANTS_BASE}/equities/bars/daily",
                params={"code": code5},
                headers={"x-api-key": self.config.jquants_key, "User-Agent": "asset-play/0.1"},
                timeout=30,
            )
        except Exception:
            return None
        if r.status_code != 200:
            return None
        data = (r.json() or {}).get("data", [])
        if not data:
            return None
        close = data[-1].get("C")
        return Decimal(str(close)) if close is not None else None
