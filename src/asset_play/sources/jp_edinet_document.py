"""SPEC-JP-001 — EDINET 有価証券報告書의 賃貸等不動産 時価 주석 파서 (pure).

일본은 한국과 달리 賃貸等不動産(임대등부동산)의 時価를 XBRL 수치태그가 아니라 텍스트블록
(``NotesRealEstateForLeaseEtc...TextBlock``) 안의 HTML 표로 공시한다(2026-06 有報 132건 전부
텍스트블록). 표는 카테고리(賃貸等不動産 / 사용겸용)마다 連結貸借対照表計上額(期首/期中増減/期末)과
期末時価를 前期·当期 2열로 담는다. 이 파서는 텍스트에서 当期의 期末 帳簿価額과 期末時価를 뽑아
含み益(=時価−帳簿)을 구한다. 단위(百万円/千円/円)는 표 머리의 '単位：…'에서 검출.

한국 dart_document(투자부동산 공정가치)의 일본 대응 — 賃貸等不動産=실현가능(투자부동산),
사용겸용=인식형(영업용 토지) 으로 분류(SPEC-NAV rev.3 AC-5와 정합).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

_NUM = re.compile(r"△?▲?-?[0-9]{1,3}(?:,[0-9]{3})+|△?▲?-?[0-9]+")
_UNIT = {"百万円": Decimal(1_000_000), "千円": Decimal(1000), "円": Decimal(1)}


def _to_won_yen(tok: str) -> Optional[Decimal]:
    """'△587'·'52,474' → Decimal. △/▲/- 는 음수."""
    neg = tok[:1] in ("△", "▲", "-")
    s = tok.lstrip("△▲-").replace(",", "")
    if not s.isdigit():
        return None
    v = Decimal(s)
    return -v if neg else v


def _unit_multiplier(text: str) -> Decimal:
    m = re.search(r"単位[：:\s]*([百万千]?円)", text)
    return _UNIT.get(m.group(1), Decimal(1_000_000)) if m else Decimal(1_000_000)


def _nums_after(label: str, text: str, start: int, n: int = 2) -> list:
    """label 직후의 숫자 n개(前期, 当期)를 순서대로."""
    i = text.find(label, start)
    if i < 0:
        return []
    seg = text[i + len(label): i + len(label) + 60]
    out = []
    for m in _NUM.finditer(seg):
        d = _to_won_yen(m.group())
        if d is not None:
            out.append(d)
        if len(out) >= n:
            break
    return out


@dataclass
class ChintaiItem:
    """한 카테고리(賃貸等不動産 or 사용겸용)의 当期 期末 帳簿価額·時価 (원 단위=엔)."""

    label: str
    book: Decimal       # 期末 連結貸借対照表計上額 (엔)
    fair: Decimal       # 期末時価 (엔)
    mixed_use: bool     # 사용겸용(영업용 포함=인식형) 여부

    @property
    def gain(self) -> Decimal:
        return self.fair - self.book


def parse_chintai_fudosan(text_block: str) -> list:
    """賃貸等不動産 텍스트블록 → [ChintaiItem]. 当期(2번째) 期末残高·期末時価를 카테고리별로.

    첫 期末残高/期末時価 쌍 = 순수 賃貸等不動産(실현가능), 두번째 = 사용겸용(인식형).
    """
    unit = _unit_multiplier(text_block)
    # 期末残高·期末時価 쌍을 순서대로 수집
    books, fairs = [], []
    pos = 0
    while True:
        nb = _nums_after("期末残高", text_block, pos)
        if len(nb) < 2:
            break
        books.append(nb[1] * unit)  # 当期
        pos = text_block.find("期末残高", pos) + 1
    pos = 0
    while True:
        nf = _nums_after("期末時価", text_block, pos)
        if len(nf) < 2:
            break
        fairs.append(nf[1] * unit)
        pos = text_block.find("期末時価", pos) + 1

    items = []
    for idx, (b, f) in enumerate(zip(books, fairs)):
        items.append(ChintaiItem(
            label="賃貸等不動産" if idx == 0 else "賃貸等不動産(사용겸용 포함)",
            book=b, fair=f, mixed_use=(idx > 0),
        ))
    return items


# --------------------------------------------------------------------------- #
# EDINET XBRL_TO_CSV 財務 추출 (스크린 1단계용; J-Quants 무료는 財務 제외)
# --------------------------------------------------------------------------- #
def _csv_find(
    csv_text: str, short: str, *, cons: Optional[str] = None,
    ctx_exact: Optional[str] = None, ctx_prefix: Optional[str] = None,
) -> Optional[Decimal]:
    """EDINET CSV(탭구분)에서 (요소ID 끝부분 × 연결구분 × 컨텍스트) 매칭 첫 수치(円)."""
    for ln in csv_text.splitlines():
        cols = [c.strip('"') for c in ln.split("\t")]
        if len(cols) < 9:
            continue
        eid, ctx, c, val = cols[0], cols[2], cols[4], cols[8]
        if eid.split(":")[-1] != short:
            continue
        if cons and c != cons:
            continue
        if ctx_exact and ctx != ctx_exact:
            continue
        if ctx_prefix and not ctx.startswith(ctx_prefix):
            continue
        d = _to_won_yen(val)
        if d is not None:
            return d
    return None


def parse_jp_financials(csv_text: str) -> dict:
    """EDINET XBRL CSV → 連結 当期 재무(円): 자산총계·순자산·지배지분·순이익·발행주식수.

    NAV/스크린 정합: 한국 연결(CFS) 기준에 맞춰 連結 사용. 지배지분=純資産−非支配持分.
    값은 EDINET XBRL 원본이 円 단위(콤마 없음) — 별도 단위보정 불필요.
    """
    assets = _csv_find(csv_text, "Assets", cons="連結", ctx_exact="CurrentYearInstant")
    net_assets = _csv_find(csv_text, "NetAssets", cons="連結", ctx_exact="CurrentYearInstant")
    nci = _csv_find(csv_text, "NonControllingInterests", cons="連結", ctx_exact="CurrentYearInstant")
    net_income = _csv_find(
        csv_text, "ProfitLossAttributableToOwnersOfParent", cons="連結",
        ctx_exact="CurrentYearDuration",
    )
    shares = _csv_find(
        csv_text, "TotalNumberOfIssuedSharesSummaryOfBusinessResults",
        ctx_prefix="CurrentYearInstant",
    )
    controlling = (
        net_assets - nci if (net_assets is not None and nci is not None) else net_assets
    )
    return {
        "assets": assets, "net_assets": net_assets, "controlling_equity": controlling,
        "net_income": net_income, "shares": shares,
    }
