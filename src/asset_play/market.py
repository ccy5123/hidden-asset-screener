"""시장 선택(KR/JP) — CLI와 Streamlit 앱이 공유하는 단일 출처.

KR과 JP는 종목코드 자리수가 달라(KR 6자리·corp_code 8자리 / JP 4자리) 충돌하지 않으므로
코드만으로 시장을 자동판별해 알맞은 어댑터를 주입한다. 자동판별이 틀리면 override(kr|jp)로 강제.
"""

from __future__ import annotations

from typing import Optional

from .config import Config


def detect_market(code: str, override: Optional[str] = None) -> str:
    """단일 코드의 시장 — JP 티커=4자리, 그 외(KR 6자리·corp 8자리)=KR. override가 우선."""
    if override:
        ov = override.strip().lower()
        if ov not in ("kr", "jp"):
            raise ValueError(f"unknown market {override!r} (use kr|jp)")
        return ov
    return "jp" if len(code.strip()) == 4 else "kr"


def resolve_market(codes: list[str], override: Optional[str] = None) -> str:
    """여러 코드의 시장 — 모두 같은 시장이어야 함(한 파이프라인=한 어댑터). 비면 KR 기본."""
    if override:
        return detect_market("", override)
    markets = {detect_market(c) for c in codes if c}
    if len(markets) > 1:
        raise ValueError("한 번에 한 시장만: KR(6자리)·JP(4자리) 종목을 섞지 마세요 (또는 시장 강제 지정)")
    return markets.pop() if markets else "kr"


def _kr_price_provider(config: Config, cache):
    """KR 시세 제공자 — price_source: auto(Yahoo 우선·KRX 폴백) | yahoo | krx.

    Cloud(해외 IP)는 KRX(data.krx.co.kr)가 차단되어 fdr 실패 → Yahoo(키 불필요)로 받는다.
    한국 IP 로컬은 KRX도 되지만 Yahoo 우선이 이식성↑(둘 다 근사 일치).
    """
    from .sources.krx import CompositePriceProvider, KrxClient
    from .sources.yahoo import YahooPriceProvider

    src = (config.price_source or "auto").lower()
    if src == "krx":
        return KrxClient(config, cache=cache)
    if src == "yahoo":
        return YahooPriceProvider(config, cache=cache)
    return CompositePriceProvider(
        [YahooPriceProvider(config, cache=cache), KrxClient(config, cache=cache)]
    )


def make_pipeline(
    config: Config,
    market: str,
    *,
    extra_landprice: Optional[list[str]] = None,
    landprice_index=None,
):
    """시장에 맞는 어댑터를 주입한 Pipeline. KR=기본(DART+KRX), JP=EDINET+J-Quants(+公示地価).

    ``landprice_index`` 를 미리 만들어 넘기면(앱이 캐시한 인덱스 등) 재로딩을 생략한다.
    """
    from .cache import CacheStore
    from .pipeline import Pipeline

    if market != "jp":
        cache = CacheStore(str(config.cache_dir / "asset_play.sqlite"))
        return Pipeline(config, price_provider=_kr_price_provider(config, cache), cache=cache)

    from .sources.adapter import JpAdapter
    from .sources.jp_edinet import EdinetClient, GsiGeocoder, JQuantsClient, recent_business_dates

    cache = CacheStore(str(config.cache_dir / "asset_play.sqlite"))
    # 公示地価 소스: reinfolib API(키 있으면 우선 — 파일 없이 Cloud OK) > GeoJSON 파일 인덱스.
    reinfolib = geocoder = None
    index = landprice_index
    if config.reinfolib_key:
        from .sources.reinfolib import ReinfolibClient

        reinfolib = ReinfolibClient(config, cache=cache)
        geocoder = GsiGeocoder(cache=cache)  # reinfolib 타일·최근접에 좌표 필요
        index = None
    elif index is None:
        files = list(extra_landprice or []) + [str(p) for p in (config.landprice_files or [])]
        if files:
            from .sources.jp_landprice import build_index_from_files

            index = build_index_from_files(*files)  # 公示地価 인덱스 (없으면 None=섹션 생략)
    adapter = JpAdapter(
        EdinetClient(config, cache=cache),
        JQuantsClient(config, cache=cache),
        dates=recent_business_dates(300),  # 有報 연1회 → ~1년 창(첫 매칭에서 멈춤)
        landprice_index=index, reinfolib=reinfolib, geocoder=geocoder,
    )
    return Pipeline(config, adapter=adapter, cache=cache)
