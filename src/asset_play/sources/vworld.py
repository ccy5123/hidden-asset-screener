"""V-World geocoder (SPEC-LAND-002): 주소 → PNU(필지고유번호 19자리).

The screener depends on the ``Geocoder`` protocol. ``VWorldClient`` is the live adapter;
``StaticGeocoder`` backs tests. Address-mismatch returns ``None`` so the caller routes the
parcel to the review queue (LAND-002 invariant — never auto-confirm a failed match).
"""

from __future__ import annotations

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
        self, mapping: Optional[dict[str, str]] = None, source_name: str = "static-geocoder"
    ) -> None:
        self.mapping = dict(mapping or {})
        self.source_name = source_name

    def address_to_pnu(self, address: str) -> Optional[str]:
        if not address:
            return None
        return self.mapping.get(address.strip())


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

    def address_to_pnu(self, address: str) -> Optional[str]:  # pragma: no cover - network/key
        if not address:
            return None
        data = self.get_json(
            VWORLD_ADDRESS_URL,
            params={
                "service": "address",
                "request": "getcoord",
                "type": "parcel",
                "address": address,
                "format": "json",
                "key": self._key(),
            },
            namespace="vworld:pnu",
            cache_key=address.strip(),
        )
        return self._parse_pnu(data)
