"""HTML report. Each company row links to its evidence (source · as_of · 가정) — AC-3."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Union

from jinja2 import Environment, select_autoescape

from ..aggregate.rank import rank_by_nav_discount
from ..domain.enums import AssetClass
from ..domain.models import NAVResult

_CLASS_LABELS = {
    AssetClass.EQUITY: "상장지분",
    AssetClass.LAND: "토지(정밀)",
    AssetClass.INVESTMENT_PROPERTY: "투자부동산",
    AssetClass.UNLISTED_EQUITY: "비상장지분",
    AssetClass.OTHER: "기타",
}

_TEMPLATE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>Asset-Play Screener — 숨은 자산가치 랭킹</title>
<style>
 body{font-family:-apple-system,'Segoe UI',Roboto,'Noto Sans KR',sans-serif;margin:24px;color:#1a1a1a}
 h1{font-size:20px} .meta{color:#666;font-size:12px;margin-bottom:16px}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border:1px solid #ddd;padding:6px 8px;text-align:right}
 th{background:#f5f5f7;text-align:center} td.l{text-align:left}
 tr:nth-child(even){background:#fafafa}
 .grade-高{color:#0a7d27;font-weight:600}.grade-中{color:#b8860b}.grade-低{color:#b00020}
 details{margin:0}.ev{font-size:12px;color:#444}
 .neg{color:#b00020}
 footer{margin-top:20px;color:#888;font-size:11px}
</style></head><body>
<h1>Asset-Play Screener — 숨은 자산가치(含み資産) 랭킹</h1>
<div class="meta">생성: {{ generated }} · 종목 수: {{ rows|length }} ·
 nav_discount = 1 − 시총 / revalued_nav (1차 신호) · revalued_nav = 별도자본총계 + 세후잉여 ·
 surplus_ratio = 세후잉여 / 시총 (보조)</div>
<table>
<thead><tr>
 <th>#</th><th>종목</th><th>시장</th><th>시가총액</th><th>revalued_nav</th><th>nav_discount</th>
 <th>상장지분</th><th>토지</th><th>투자부동산</th><th>비상장</th>
 <th>실현가능</th><th>인식형</th>
 <th>세전</th><th>세후</th><th>surplus_ratio</th>
 <th>신뢰도</th><th>검토큐</th><th>근거</th>
</tr></thead>
<tbody>
{% for r in rows %}
<tr>
 <td>{{ loop.index }}</td>
 <td class="l">{{ r.name }}{% if r.stock_code %} <small>({{ r.stock_code }})</small>{% endif %}</td>
 <td>{{ r.market }}</td>
 <td>{{ r.market_cap }}</td>
 <td>{{ r.revalued_nav }}</td>
 <td>{{ r.nav_discount }}</td>
 <td>{{ r.equity_gain }}</td>
 <td>{{ r.land_gain }}</td>
 <td>{{ r.ip_gain }}</td>
 <td>{{ r.unlisted_gain }}</td>
 <td>{{ r.realizable }}</td>
 <td>{{ r.recognition }}</td>
 <td>{{ r.pretax }}</td>
 <td class="{{ 'neg' if r.net_surplus_neg }}">{{ r.net_surplus }}</td>
 <td>{{ r.surplus_ratio }}</td>
 <td class="grade-{{ r.confidence }}">{{ r.confidence }}</td>
 <td>{{ r.review_queue_count }}</td>
 <td class="l"><details><summary>{{ r.evidence|length }} sources</summary>
   <div class="ev">
   {% for e in r.evidence %}• {{ e.source }} · {{ e.as_of }} · {{ e.method }}
     {%- if e.assumptions %} · {{ e.assumptions }}{% endif %}<br>{% endfor %}
   <b>가정:</b> {{ r.assumptions }}
   {% if r.warnings %}<br><b>경고:</b> {{ r.warnings }}{% endif %}
   </div></details></td>
</tr>
{% endfor %}
</tbody></table>
<footer>⚠️ 리서치·스크리닝 보조용. 투자 자문 아님. 토지 정밀 NAV는 사람 검토(human-in-loop) 전제.
 프록시(低) 종목과 정밀(高) 종목을 신뢰도 등급으로 구분해 해석할 것.</footer>
</body></html>
"""


def _class_gain(r: NAVResult, ac: AssetClass) -> Decimal:
    agg = r.by_class.get(ac)
    return agg.unrealized_gain if agg else Decimal(0)


def _view(r: NAVResult) -> dict:
    return {
        "name": r.name,
        "stock_code": r.stock_code or "",
        "market": r.market.value,
        "market_cap": f"{r.market_cap:,}" if r.market_cap is not None else "—",
        "revalued_nav": f"{r.revalued_nav:,}" if r.revalued_nav is not None else "—",
        "nav_discount": f"{r.nav_discount:.1%}" if r.nav_discount is not None else "—",
        "equity_gain": f"{_class_gain(r, AssetClass.EQUITY):,}",
        "land_gain": f"{_class_gain(r, AssetClass.LAND):,}",
        "ip_gain": f"{_class_gain(r, AssetClass.INVESTMENT_PROPERTY):,}",
        "unlisted_gain": f"{_class_gain(r, AssetClass.UNLISTED_EQUITY):,}",
        "realizable": f"{r.realizable_surplus:,}",
        "recognition": f"{r.recognition_only_surplus:,}",
        "pretax": f"{r.total_unrealized_pretax:,}",
        "net_surplus": f"{r.net_surplus:,}",
        "net_surplus_neg": r.net_surplus < 0,
        "surplus_ratio": f"{r.surplus_ratio:.2%}" if r.surplus_ratio is not None else "—",
        "confidence": r.overall_confidence.value if r.overall_confidence else "—",
        "review_queue_count": r.review_queue_count,
        "evidence": [
            {
                "source": e.source,
                "as_of": e.as_of_date.isoformat(),
                "method": e.method,
                "assumptions": e.assumptions or {},
            }
            for e in r.evidence
        ],
        "assumptions": r.assumptions,
        "warnings": " | ".join(r.warnings),
    }


def render_html(results: list[NAVResult], *, generated: Optional[str] = None) -> str:
    env = Environment(autoescape=select_autoescape(["html"]))
    template = env.from_string(_TEMPLATE)
    ordered = rank_by_nav_discount(results)
    return template.render(
        rows=[_view(r) for r in ordered],
        generated=generated or date.today().isoformat(),
    )


def write_html(results: list[NAVResult], path: Union[str, Path], **kwargs) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(results, **kwargs), encoding="utf-8")
    return path
