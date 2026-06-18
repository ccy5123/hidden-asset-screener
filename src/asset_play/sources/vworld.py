"""V-World geocoder (SPEC-LAND-002): 주소 → PNU(필지고유번호 19자리).

The screener depends on the ``Geocoder`` protocol. ``VWorldClient`` is the live adapter;
``StaticGeocoder`` backs tests. Address-mismatch returns ``None`` so the caller routes the
parcel to the review queue (LAND-002 invariant — never auto-confirm a failed match).
"""

from __future__ import annotations

import re
from typing import Optional, Protocol, runtime_checkable

from ..exceptions import ConfigError
from .base import HttpSource

VWORLD_ADDRESS_URL = "https://api.vworld.kr/req/address"


@runtime_checkable
class Geocoder(Protocol):
    source_name: str

    def address_to_pnu(self, address: str) -> Optional[str]: ...


class StaticGeocoder:
    """In-memory address → PNU map. Unknown addresses return ``None`` (→ review queue)."""

    def __init__(
        self,
        mapping: Optional[dict[str, str]] = None,
        source_name: str = "static-geocoder",
        match_type: str = "parcel",
    ) -> None:
        self.mapping = dict(mapping or {})
        self.source_name = source_name
        self.match_type = match_type  # "parcel"(지번, 정확) | "road"(도로명, 저신뢰)
        self.last_match_type: Optional[str] = None

    def address_to_pnu(self, address: str) -> Optional[str]:
        pnu = self.mapping.get(address.strip()) if address else None
        self.last_match_type = self.match_type if pnu else None
        return pnu


class VWorldClient(HttpSource):
    source_name = "V-World"

    def _key(self) -> str:
        if not self.config.vworld_key:
            raise ConfigError("V-World key missing (set ASSET_PLAY_VWORLD_KEY)")
        return self.config.vworld_key

    @staticmethod
    def _parse_pnu(payload: dict) -> Optional[str]:
        """Extract PNU from a V-World getcoord response. Kept separate for tests.

        The 19-digit PNU is at ``response.refined.structure.level4LC`` (``result`` only
        holds x/y coordinates). Road-type addresses leave level4LC blank → None.
        """
        try:
            resp = payload["response"]
            if resp.get("status") != "OK":
                return None
            pnu = resp.get("refined", {}).get("structure", {}).get("level4LC")
            return pnu or None
        except (KeyError, TypeError, AttributeError):
            return None

    @staticmethod
    def _construct_pnu(ldcode: Optional[str], jibun: Optional[str]) -> Optional[str]:
        """법정동코드(10) + 지번('41-2','산5-3','1') → 19자리 PNU.

        PNU = 법정동코드(10) + 필지구분(1: 일반=1, 산=2) + 본번(4) + 부번(4).
        """
        if not ldcode or len(ldcode) < 10 or not jibun:
            return None
        m = re.search(r"(산)?\s*(\d+)(?:-(\d+))?", str(jibun))
        if not m:
            return None
        san = "2" if m.group(1) else "1"
        return f"{ldcode[:10]}{san}{m.group(2).zfill(4)}{(m.group(3) or '0').zfill(4)}"

    @staticmethod
    def _parse_point(payload: dict) -> Optional[tuple[str, str]]:
        try:
            resp = payload["response"]
            if resp.get("status") != "OK":
                return None
            pt = resp.get("result", {}).get("point")
            return (pt["x"], pt["y"]) if pt else None
        except (KeyError, TypeError):
            return None

    @classmethod
    def _parse_reverse_pnu(cls, payload: dict) -> Optional[str]:
        try:
            resp = payload["response"]
            if resp.get("status") != "OK":
                return None
            items = resp.get("result", [])
            if isinstance(items, dict):
                items = [items]
            st = items[0].get("structure", {}) if items else {}
            return cls._construct_pnu(st.get("level4LC"), st.get("level5"))
        except (KeyError, TypeError, IndexError):
            return None

    def address_to_pnu(self, address: str) -> Optional[str]:  # pragma: no cover - network/key
        # last_match_type: "parcel"(지번, 정확) | "road"(도로명, 인접필지 오매칭 위험) | None
        self.last_match_type: Optional[str] = None
        if not address:
            return None
        addr = address.strip()
        # 1) 지번주소 직접 매칭 (정확)
        data = self.get_json(
            VWORLD_ADDRESS_URL,
            params={"service": "address", "request": "getcoord", "type": "parcel",
                    "address": addr, "format": "json", "key": self._key()},
            namespace="vworld:pnu",
            cache_key=addr,
        )
        pnu = self._parse_pnu(data)
        if pnu:
            self.last_match_type = "parcel"
            return pnu
        # 2) 도로명주소 → 좌표 → 역지오코딩 → PNU 구성 (저신뢰: 도로 좌표가 인접 필지를 잡을 수 있음).
        rd = self.get_json(
            VWORLD_ADDRESS_URL,
            params={"service": "address", "request": "getcoord", "type": "road",
                    "address": addr, "format": "json", "key": self._key()},
            namespace="vworld:road",
            cache_key=addr,
        )
        point = self._parse_point(rd)
        if not point:
            return None
        rev = self.get_json(
            VWORLD_ADDRESS_URL,
            params={"service": "address", "request": "getAddress", "point": f"{point[0]},{point[1]}",
                    "crs": "EPSG:4326", "type": "parcel", "format": "json", "key": self._key()},
            namespace="vworld:rev",
            cache_key=f"{point[0]},{point[1]}",
        )
        pnu = self._parse_reverse_pnu(rev)
        self.last_match_type = "road" if pnu else None
        return pnu
