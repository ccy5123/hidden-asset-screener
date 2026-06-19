"""SPEC-JP-001 — 賃貸等不動産 時価 텍스트블록 파서 (pure). 실데이터: 西日本鉄道(9031)."""

from decimal import Decimal

from asset_play.sources.jp_edinet_document import ChintaiItem, parse_chintai_fudosan

# 西日本鉄道 2026-03기 有報 賃貸等不動産 텍스트블록 실제 발췌 (単위：百万円). 숫자는 前期当期 연접.
NISHITETSU = (
    "(賃貸等不動産関係)当社及び一部の連結子会社では…賃貸等不動産及び賃貸等不動産として使用される"
    "部分を含む不動産に関する連結貸借対照表計上額、期中増減額及び時価は次のとおりです。 "
    "(単位：百万円) 前連結会計年度当連結会計年度"
    "賃貸等不動産連結貸借対照表計上額期首残高53,06152,474期中増減額△5871,315"
    "期末残高52,47453,789期末時価91,02891,753"
    "賃貸等不動産として使用される部分を含む不動産連結貸借対照表計上額"
    "期首残高29,857116,823期中増減額86,9653,742期末残高116,823120,566期末時価218,998223,297"
)


def test_parses_two_categories_current_year():
    items = parse_chintai_fudosan(NISHITETSU)
    assert len(items) == 2

    chintai = items[0]
    assert chintai.mixed_use is False
    assert chintai.book == Decimal("53789000000")   # 当期 期末残高 53,789 백만엔
    assert chintai.fair == Decimal("91753000000")   # 当期 期末時価 91,753 백만엔
    assert chintai.gain == Decimal("37964000000")   # 含み益 +380억엔

    mixed = items[1]
    assert mixed.mixed_use is True
    assert mixed.book == Decimal("120566000000")
    assert mixed.fair == Decimal("223297000000")
    assert mixed.gain == Decimal("102731000000")    # +1,027억엔


def test_unit_thousand_yen():
    txt = "(単位：千円) 期末残高1,0002,000期末時価3,0007,000"
    items = parse_chintai_fudosan(txt)
    assert items[0].book == Decimal("2000000")      # 2,000 천엔
    assert items[0].fair == Decimal("7000000")
    assert items[0].gain == Decimal("5000000")


def test_empty_or_omission_textblock_yields_nothing():
    # 重要性 부족 생략 케이스(川崎汽船식): 期末残高/期末時価 표 없음
    assert parse_chintai_fudosan("当社では重要性が乏しいため記載を省略しています。") == []


def test_chintai_item_gain():
    it = ChintaiItem(label="x", book=Decimal("100"), fair=Decimal("250"), mixed_use=False)
    assert it.gain == Decimal("150")
