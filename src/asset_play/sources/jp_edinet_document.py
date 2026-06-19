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
