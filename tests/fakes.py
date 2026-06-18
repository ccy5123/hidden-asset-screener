"""Test doubles: deterministic HTTP session + DART, and a synthetic corpCode zip."""

from __future__ import annotations

import io
import zipfile
from typing import Callable, Optional

from asset_play.domain.models import Company, EquityHolding


class FakeResponse:
    def __init__(self, *, status_code=200, json_data=None, content=b"", text=""):
        self.status_code = status_code
        self._json = json_data
        self._content = content
        self._text = text

    def json(self):
        return self._json

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        return self._text


class FakeSession:
    """Either pops queued responses in order, or delegates to a ``handler(url, params)``.

    A queued item that is an ``Exception`` is raised (to exercise retry paths).
    """

    def __init__(self, responses=None, handler: Optional[Callable] = None):
        self.responses = list(responses or [])
        self.handler = handler
        self.calls: list[tuple[str, Optional[dict]]] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        item = self.handler(url, params) if self.handler else self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_corpcode_zip(rows: list[tuple[str, str, str]]) -> bytes:
    """rows: (corp_code, corp_name, stock_code). Empty stock_code → unlisted."""
    parts = ["<result>"]
    for cc, name, stock in rows:
        parts.append(
            f"<list><corp_code>{cc}</corp_code><corp_name>{name}</corp_name>"
            f"<stock_code>{stock}</stock_code><modify_date>20240101</modify_date></list>"
        )
    parts.append("</result>")
    xml = "".join(parts).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml)
    return buf.getvalue()


class FakeDart:
    """In-memory stand-in for DartClient (regression/pipeline tests, no network)."""

    def __init__(
        self,
        company: Company,
        holdings: list[EquityHolding],
        *,
        stock_to_corp=None,
        name_to_stock=None,
        name_to_corp=None,
        net_assets_by_corp=None,
        separate_equity_by_corp=None,
    ):
        self.company = company
        self.holdings = holdings
        self.stock_to_corp = stock_to_corp or {}
        self.name_to_stock = name_to_stock or {}
        self.name_to_corp = name_to_corp or {}
        self.net_assets_by_corp = net_assets_by_corp or {}
        self.separate_equity_by_corp = separate_equity_by_corp or {}

    def corp_code_for_stock(self, stock_code):
        return self.stock_to_corp.get(stock_code)

    def get_company(self, corp_code):
        return self.company

    def get_other_corp_investments(self, corp_code, bsns_year, reprt_code):
        return list(self.holdings)

    def stock_code_for_name(self, name):
        return self.name_to_stock.get(name)

    def corp_code_for_name(self, name):
        return self.name_to_corp.get(name)

    def get_net_assets(self, corp_code, bsns_year, reprt_code):
        return self.net_assets_by_corp.get(corp_code)

    def get_separate_total_equity(self, corp_code, bsns_year, reprt_code):
        return self.separate_equity_by_corp.get(corp_code)

    def get_disclosures(self, corp_code, bgn_de, end_de):
        return list(getattr(self, "disclosures", []) or [])
