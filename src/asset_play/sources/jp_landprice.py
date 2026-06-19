"""SPEC-JP-002 — 일본 영업용 토지 含み益 추정용 公示地価/地価調査 인덱스 (보수적).

国土数値情報 L01(地価公示)/L02(都道府県地価調査) GeoJSON(키 불필요, 무료 일괄)에서 標準地·基準地의
円/㎡를 받아 市区町村×用途 인덱스를 만든다. 有報 設備현황의 (所在地·면적·취득원가·시설용도)와 매칭해
推定시가 = 円/㎡ × 면적, 含み益 = 추정−취득원가 를 구한다.

たーちゃん식 '거친 含み益' 자동화 — 정밀 감정이 아니라 스크리닝 신호. 그래서 **보수적**:
- 공장/車庫/倉庫 토지는 工業 표준지 우선, 없으면 주택가×할인(공장<주택).
- 公示地価 그대로(도시 시가배율 미적용). 신뢰도 🟡(用途 직접매칭)/🔴(할인 폴백·미커버).
한국 V-World 개별공시지가의 일본판이지만, 일본은 표본 標準地라 필지 정밀이 아닌 구 median 근사.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

# 시설 用途 → 카테고리. 標準地 用途(L02_025: '住宅','工場','住宅,店舗' 등)도 같은 키워드로 분류.
_INDUSTRIAL = ("工場", "倉庫", "作業場", "車庫", "物流", "工業", "準工", "工専", "ロジ", "センター", "営業所")
_COMMERCIAL = ("商業", "店舗", "事務所", "銀行", "旅館", "ホテル", "百貨店", "ビル",
               "ターミナル", "近商", "オフィス", "テナント", "給油")
_RESIDENTIAL = ("住宅", "医院", "マンション", "居住", "シニア", "アパート", "宅地")
# 用途 표준지 없을 때 기준 median에 곱하는 보수 할인(공업지<주택지<상업지). 기준=주거 median 우선.
_DISCOUNT = {"industrial": Decimal("0.6"), "commercial": Decimal("1.3"), "residential": Decimal("1")}

_PREF = re.compile(r"^(東京都|北海道|京都府|大阪府|.{2,3}県)")
_MUNI = re.compile(r"(\S+?市\S*?区|\S+?市|\S+?区|\S+?郡\S+?[町村]|\S+?[町村])")


def category_of(text: Optional[str]) -> str:
    """用途/시설명 → industrial|commercial|residential|other."""
    t = text or ""
    if any(k in t for k in _INDUSTRIAL):
        return "industrial"
    if any(k in t for k in _COMMERCIAL):
        return "commercial"
    if any(k in t for k in _RESIDENTIAL):
        return "residential"
    return "other"


def muni_token(addr: Optional[str]) -> Optional[str]:
    """주소에서 都道府県 제거 후 市区町村 토큰. '福岡県筑紫野市'→'筑紫野市', '福岡市東区'→'福岡市東区'."""
    if not addr:
        return None
    s = addr.replace("　", "").replace(" ", "")
    s = _PREF.sub("", s, count=1)
    m = _MUNI.match(s)
    return m.group(1) if m else None


@dataclass
class LandPricePoint:
    muni: str        # 市区町村 토큰
    use: str         # 標準地 用途 원문
    price: Decimal   # 円/㎡


class JpLandPriceIndex:
    """市区町村 × 카테고리 → 円/㎡ median 인덱스 (보수적 폴백 포함)."""

    def __init__(self, points: list) -> None:
        self.by_muni: dict = {}
        for p in points:
            cat = category_of(p.use)
            b = self.by_muni.setdefault(p.muni, {})
            b.setdefault(cat, []).append(p.price)
            b.setdefault("ALL", []).append(p.price)

    def _bucket(self, muni: Optional[str]) -> Optional[dict]:
        if not muni:
            return None
        b = self.by_muni.get(muni)
        if b:
            return b
        for k, v in self.by_muni.items():  # 부분일치 폴백
            if muni in k or k in muni:
                return v
        return None

    def price_per_sqm(self, muni: Optional[str], category: str) -> tuple:
        """(円/㎡ Decimal|None, confidence 'med'|'low', matched 설명).

        用途 직접매칭(med) 우선. 없으면 **주거 median**(가장 흔한 표준지) 기준 × 用途 비율로 보수 추정.
        주거도 없으면 ALL median × 비율. (공업≈주거×0.6, 상업≈주거×1.3)
        """
        b = self._bucket(muni)
        if not b:
            return (None, "low", "미커버")
        if b.get(category):
            return (Decimal(int(statistics.median(b[category]))), "med", category)
        base = b.get("residential")
        base_label = "주거"
        if not base:
            base = b.get("ALL")
            base_label = "전체"
        if not base:
            return (None, "low", "미커버")
        disc = _DISCOUNT.get(category, Decimal("0.8"))
        price = (Decimal(int(statistics.median(base))) * disc).quantize(Decimal(1))
        return (price, "low", f"{base_label}×{disc}(用途 표준지 없음)")


@dataclass
class OperatingLandEstimate:
    location: str
    area: Decimal           # ㎡
    book: Decimal           # 円 (취득원가)
    category: str
    price_per_sqm: Optional[Decimal]
    estimate: Optional[Decimal]   # 円
    confidence: str          # med|low
    matched: str

    @property
    def gain(self) -> Optional[Decimal]:
        return (self.estimate - self.book) if self.estimate is not None else None


def estimate_operating_land(facilities: list, index: JpLandPriceIndex) -> list:
    """facilities: [(location, area㎡, book円, category)] → [OperatingLandEstimate]."""
    out = []
    for loc, area, book, cat in facilities:
        pps, conf, matched = index.price_per_sqm(muni_token(loc), cat)
        est = (pps * Decimal(area)) if (pps is not None and area) else None
        out.append(OperatingLandEstimate(
            location=loc, area=Decimal(area), book=Decimal(book), category=cat,
            price_per_sqm=pps, estimate=est, confidence=conf, matched=matched,
        ))
    return out


def _detect_address(props: dict) -> Optional[str]:
    """프로퍼티 중 都道府県+市区町村 형태의 전체 주소(예: L02_022/L01_xxx) 자동 탐지."""
    for v in props.values():
        if isinstance(v, str) and _PREF.match(v.replace("　", "")) and _MUNI.search(v.replace("　", "")):
            return v
    return None


def _detect_use(props: dict) -> str:
    """프로퍼티 중 짧은 用途값(住宅/商業/工場/店舗…) 자동 탐지. 없으면 ''."""
    for v in props.values():
        if isinstance(v, str) and 0 < len(v) <= 16 and category_of(v) != "other":
            return v
    return ""


def load_landprice_geojson(geojson_path: str) -> list:
    """L01(地価公示)/L02(地価調査) GeoJSON → [LandPricePoint] (범용 — 필드코드 무관).

    当年 価格은 L01_006/L02_006(国土数値情報 공통). 주소·用途는 내용으로 탐지 → L01/L02 둘 다 처리.
    """
    d = json.load(open(geojson_path, encoding="utf-8"))
    points = []
    for f in d.get("features", []):
        p = f.get("properties", {})
        price = p.get("L01_006", p.get("L02_006"))  # 当年 公示価格/基準地価格 (円/㎡)
        mu = muni_token(_detect_address(p))
        if mu and isinstance(price, (int, float)) and price > 0:
            points.append(LandPricePoint(muni=mu, use=_detect_use(p), price=Decimal(int(price))))
    return points


def load_l02_points(geojson_path: str) -> list:
    """하위호환 별칭 — 범용 로더로 위임."""
    return load_landprice_geojson(geojson_path)


def build_index_from_files(*geojson_paths: str) -> "JpLandPriceIndex":
    """여러 GeoJSON(L01+L02)을 병합해 단일 인덱스 — 커버리지↑."""
    pts: list = []
    for path in geojson_paths:
        pts.extend(load_landprice_geojson(path))
    return JpLandPriceIndex(pts)
