"""reinfolib (国土交通省 부동산정보 라이브러리) XPT002 — JP 地価公示/地価調査 포인트 API.

키 불필요 GeoJSON(L01/L02 파일) 대신 API로 地価를 받아 **파일 없이 Cloud에서도** JP 영업용 토지
含み益을 추정한다. 타일(z/x/y) GeoJSON 반환 — 시설 좌표가 든 타일을 조회해 인근 標準地 円/㎡를 얻는다.

[HARD] 인증은 헤더(``Ocp-Apim-Subscription-Key``) — 키가 URL/params에 안 실려 API 원문 패널에도 비노출.
"""

from __future__ import annotations

import math
import re
import time
from datetime import date
from decimal import Decimal
from typing import Optional

from ..config import Config
from ..exceptions import ConfigError
from .jp_landprice import LandPricePoint
from .recorder import active_recorder, record

_BASE = "https://www.reinfolib.mlit.go.jp/ex-api/external/XPT002"
_PRICE_NUM = re.compile(r"[\d,]+")


def _tile(lat: float, lon: float, z: int) -> tuple:
    """위경도 → XYZ 타일 좌표 (웹메르카토르)."""
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def _price(props: dict) -> Optional[Decimal]:
    """当年 円/㎡ — 'u_current_years_price_ja'(예 '36,800,000(円/㎡)') 파싱, 없으면 작년 정수 폴백."""
    s = props.get("u_current_years_price_ja")
    if isinstance(s, str):
        m = _PRICE_NUM.search(s)
        if m and m.group(0).replace(",", ""):
            return Decimal(m.group(0).replace(",", ""))
    v = props.get("last_years_price")
    return Decimal(int(v)) if isinstance(v, (int, float)) and v > 0 else None


def _muni(props: dict) -> Optional[str]:
    """市区町村 토큰 — 시/군 + 구 결합 (예 '福岡市'+'東区'='福岡市東区', ''+'千代田区'='千代田区')."""
    muni = ((props.get("city_county_name_ja") or "") + (props.get("ward_town_village_name_ja") or "")).strip()
    return muni or None


class ReinfolibClient:
    """XPT002 地価 포인트 — 타일 GeoJSON → [LandPricePoint]. 결과는 캐시(타일·연도 단위)."""

    source_name = "reinfolib"

    def __init__(self, config: Optional[Config] = None, *, cache=None, z: int = 13) -> None:
        self.config = config or Config()
        self.cache = cache
        self.z = z

    def _key(self) -> str:
        if not self.config.reinfolib_key:
            raise ConfigError("reinfolib key missing (set ASSET_PLAY_REINFOLIB_KEY)")
        return self.config.reinfolib_key

    def default_year(self) -> int:
        # 当年 公示는 3월 공시라 연초엔 미공개 가능 → 기본은 작년(항상 공시됨).
        return self.config.reinfolib_year or (date.today().year - 1)

    def land_points(self, lat: float, lon: float, *, year: Optional[int] = None) -> list:
        """(lat,lon)이 든 타일의 標準地·基準地 → [LandPricePoint]. 키 미설정/실패 시 []."""
        year = year or self.default_year()
        x, y = _tile(lat, lon, self.z)
        ck = f"{self.z}:{x}:{y}:{year}"
        if self.cache is not None:
            hit = self.cache.get_json("reinfolib:xpt002", ck)
            if hit is not None:
                return [LandPricePoint(p["muni"], p["use"], Decimal(p["price"]), p["lat"], p["lon"])
                        for p in hit]

        import requests

        params = {"response_format": "geojson", "z": self.z, "x": x, "y": y, "year": year}
        rec_on = active_recorder() is not None
        t0 = time.perf_counter()
        try:
            r = requests.get(_BASE, params=params,  # 키는 헤더 — params/URL에 비노출
                             headers={"Ocp-Apim-Subscription-Key": self._key(),
                                      "User-Agent": "asset-play/0.1"}, timeout=30)
        except Exception as exc:  # noqa: BLE001 — 네트워크 실패는 추정 생략으로 degrade
            if rec_on:
                record("reinfolib", _BASE, params=params, ok=False,
                       elapsed_ms=(time.perf_counter() - t0) * 1000,
                       preview=f"ERROR: {type(exc).__name__}: {exc}")
            return []
        if rec_on:
            record("reinfolib", _BASE, params=params, status=r.status_code, ok=r.status_code == 200,
                   elapsed_ms=(time.perf_counter() - t0) * 1000,
                   preview=(f"{len(r.text):,} bytes" if r.status_code == 200 else r.text[:200]))
        if r.status_code != 200:
            return []
        feats = (r.json() or {}).get("features", [])
        points = []
        for f in feats:
            p = f.get("properties") or {}
            price, muni = _price(p), _muni(p)
            c = (f.get("geometry") or {}).get("coordinates")
            if price and muni and isinstance(c, list) and len(c) >= 2:
                points.append(LandPricePoint(muni=muni, use=(p.get("use_category_name_ja") or ""),
                                             price=price, lat=c[1], lon=c[0]))
        if self.cache is not None:
            self.cache.set_json("reinfolib:xpt002", ck, [
                {"muni": p.muni, "use": p.use, "price": str(p.price), "lat": p.lat, "lon": p.lon}
                for p in points
            ])
        return points
