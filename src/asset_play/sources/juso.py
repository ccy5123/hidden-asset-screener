"""행정안전부 도로명주소 검색API — 도로명/지번 주소 → 정확 PNU (SPEC-LAND-002).

V-World 역지오코딩은 도로 좌표가 인접 필지를 잡아 부정확하다. juso 검색API는 입력 주소에
대해 admCd(법정동코드)·지번본번(lnbrMnnm)·지번부번(lnbrSlno)·산여부(mtYn)를 직접 돌려주므로
PNU를 좌표 없이 정확히 구성한다. Geocoder 프로토콜(address_to_pnu)을 구현한다.

PNU(19) = 법정동코드(10) + 필지구분(1: 일반=1, 산=2) + 본번(4) + 부번(4).
"""

from __future__ import annotations

from typing import Optional

from ..exceptions import ConfigError
from .base import HttpSource

JUSO_SEARCH_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"


class JusoClient(HttpSource):
    source_name = "juso(도로명주소)"

    def _key(self) -> str:
        if not self.config.juso_key:
            raise ConfigError("juso key missing (set ASSET_PLAY_JUSO_KEY)")
        return self.config.juso_key

    @staticmethod
    def _parse_pnu(payload: dict) -> Optional[str]:
        results = payload.get("results", {}) if isinstance(payload, dict) else {}
        if results.get("common", {}).get("errorCode") != "0":
            return None
        juso = results.get("juso") or []
        if not juso:
            return None
        j = juso[0]
        admcd = (j.get("admCd") or "").strip()
        bon = (j.get("lnbrMnnm") or "").strip()
        if len(admcd) < 10 or not bon:
            return None
        san = "2" if str(j.get("mtYn")).strip() == "1" else "1"
        bu = (j.get("lnbrSlno") or "0").strip() or "0"
        return f"{admcd[:10]}{san}{bon.zfill(4)}{bu.zfill(4)}"

    def address_to_pnu(self, address: str) -> Optional[str]:  # pragma: no cover - network/key
        # juso는 정확한 지번을 돌려주므로 항상 high-confidence("parcel")로 표시.
        self.last_match_type: Optional[str] = None
        if not address:
            return None
        data = self.get_json(
            JUSO_SEARCH_URL,
            params={
                "confmKey": self._key(),
                "currentPage": "1",
                "countPerPage": "5",
                "keyword": address.strip(),
                "resultType": "json",
            },
            namespace="juso:pnu",
            cache_key=address.strip(),
        )
        pnu = self._parse_pnu(data)
        self.last_match_type = "parcel" if pnu else None
        return pnu
