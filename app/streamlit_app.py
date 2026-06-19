"""Asset-Play 숨은자산 스크리너 — Streamlit UI.

한국(DART/KRX)·일본(EDINET/J-Quants)을 같은 화면에서. 종목코드 자리수로 시장 자동판별
(KR 6자리 / JP 4자리), 또는 사이드바에서 강제. 모든 실행은 내부 API 호출을 기록(tap)하여
"🔍 API 원문 호출" 패널에서 요청/응답 원문을 확인할 수 있다(키는 *** 마스킹).

실행:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

# 프로젝트 루트(앱 파일 기준) — 실행 위치(cwd)와 무관하게 .env·.cache·src를 여기에 고정.
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _bootstrap_env() -> None:
    """프로젝트 루트의 .env를 os.environ에 주입(실행 위치 무관) — 키를 따로 입력할 필요 없음.

    실제 환경변수가 우선(setdefault). streamlit을 어느 디렉터리에서 띄워도 내 .env가 적용된다.
    """
    env = _ROOT / ".env"
    if not env.is_file():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ").strip()
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key:
            os.environ.setdefault(key, val)


_bootstrap_env()

from asset_play.config import Config  # noqa: E402
from asset_play.exceptions import SourceError  # noqa: E402
from asset_play.market import make_pipeline, resolve_market  # noqa: E402
from asset_play.report import frames  # noqa: E402
from asset_play.report.csv_report import results_to_dataframe  # noqa: E402
from asset_play.report.markdown_report import build_company_report, render_markdown  # noqa: E402
from asset_play.sources.recorder import use_recorder  # noqa: E402
from asset_play.valuation.screen import value_screen  # noqa: E402

st.set_page_config(page_title="Asset-Play 숨은자산 스크리너", page_icon="🏢", layout="wide")

_MARKET_OVERRIDE = {"자동 (코드 자리수)": None, "한국 (KR)": "kr", "일본 (JP)": "jp"}


@st.cache_resource(show_spinner="公示地価 인덱스 로딩 중… (최초 1회)")
def _load_landprice_index(paths: tuple):
    """L01/L02 GeoJSON → JpLandPriceIndex. 경로 튜플 기준으로 캐시(재실행 시 재로딩 생략)."""
    from asset_play.sources.jp_landprice import build_index_from_files

    return build_index_from_files(*paths)


# --------------------------------------------------------------------------- #
# Sidebar — 키(.env 우선 + 보완) · 시장 · 연도 · JP GeoJSON
# --------------------------------------------------------------------------- #
def _sidebar() -> tuple:
    st.sidebar.title("⚙️ 설정")
    base = Config.from_env()

    st.sidebar.subheader("API 키")
    st.sidebar.caption(
        f"프로젝트 .env 자동 사용 ({_ROOT / '.env'}). 아래는 .env에 없는 키만 임시 보완(세션에만, 저장 안 함)."
    )
    key_specs = [
        ("dart_api_key", "DART (KR 공시·재무)"),
        ("edinet_key", "EDINET (JP 有報)"),
        ("jquants_key", "J-Quants (JP 주가)"),
        ("vworld_key", "V-World (KR 공시지가·면적)"),
        ("juso_key", "juso (KR 도로명주소)"),
    ]
    overrides: dict = {}
    for field, label in key_specs:
        present = bool(getattr(base, field))
        status = "✅ .env" if present else "— 미설정"
        val = st.sidebar.text_input(
            f"{label}  ({status})", value="", type="password",
            placeholder="비우면 .env 사용", key=f"k_{field}",
        )
        if val:
            overrides[field] = val

    st.sidebar.subheader("시장 / 연도")
    market_label = st.sidebar.radio("시장 판별", list(_MARKET_OVERRIDE), index=0)
    market_override = _MARKET_OVERRIDE[market_label]
    year = st.sidebar.text_input("사업연도", value="", placeholder="비우면 작년").strip() or None

    st.sidebar.subheader("JP 公示地価 GeoJSON (선택)")
    st.sidebar.caption("国土数値情報 L01/L02 로컬 경로 — 줄/쉼표로 여러 개. 영업용 토지 含み益 추정용.")
    default_lp = "\n".join(str(p) for p in base.landprice_files)
    landprice_raw = st.sidebar.text_area("GeoJSON 경로", value=default_lp, height=80)

    cfg = Config.from_env()
    # 캐시를 프로젝트 루트에 고정(실행 위치 무관) — corpCode 동기화 캐시 등 재사용.
    if not cfg.cache_dir.is_absolute():
        cfg.cache_dir = _ROOT / cfg.cache_dir
    for field, val in overrides.items():
        setattr(cfg, field, val)
    paths = [p.strip() for p in landprice_raw.replace("\n", ",").split(",") if p.strip()]
    if paths:
        cfg.landprice_files = [Path(p) for p in paths]
    return cfg, market_override, year


def _ensure_kr_corpcodes(pipe) -> None:
    """KR: corpCode↔stock 맵이 없으면 1회 자동 동기화(이후 캐시). 없으면 종목 해석 불가→'데이터 없음'.

    CLI는 `sync-corp-codes`를 먼저 돌리지만, 앱은 사용자가 모르게 자동 처리한다. JP는 불필요.
    """
    try:
        pipe.dart.corp_code_for_stock("000000")  # 미존재 코드 — 맵 존재 여부만 확인(None이면 동기화됨)
        return
    except SourceError:
        pass  # "corp codes not synced" → 아래에서 1회 동기화
    with st.spinner("DART corpCode 동기화 (최초 1회, 캐시됨)…"):
        pipe.sync_corp_codes()


def _jp_index(cfg: Config):
    """JP용 公示地価 인덱스(있으면) — 캐시 경유. 파일 없음/손상은 graceful(None=영업용 토지 섹션 생략)."""
    present = [p for p in (cfg.landprice_files or []) if Path(p).is_file()]
    missing = [str(p) for p in (cfg.landprice_files or []) if not Path(p).is_file()]
    if missing:
        st.warning("GeoJSON 경로를 찾을 수 없음 (영업용 토지 추정 생략): " + ", ".join(missing))
    if not present:
        return None
    # 캐시 키 정규화(절대경로·정렬) — 경로 순서/형태가 달라도 동일 인덱스 재사용(결정론).
    paths = tuple(sorted(str(Path(p).resolve()) for p in present))
    try:
        return _load_landprice_index(paths)
    except Exception as exc:  # noqa: BLE001 — 손상/읽기불가 GeoJSON도 추적 traceback 대신 graceful degrade
        st.error(f"公示地価 GeoJSON 로드 실패 (영업용 토지 추정 생략): {type(exc).__name__}: {exc}")
        return None


# --------------------------------------------------------------------------- #
# 공통 렌더
# --------------------------------------------------------------------------- #
def _render_api_log(rec) -> None:
    calls = list(getattr(rec, "calls", []) or [])
    net = [c for c in calls if not c.cache_hit]
    with st.expander(f"🔍 API 원문 호출 ({len(calls)}건 · 네트워크 {len(net)}건) — 근거 추적", expanded=False):
        if not calls:
            st.caption("기록된 호출 없음 (네트워크 미발생).")
            return
        st.dataframe(frames.api_calls_frame(rec), hide_index=True, use_container_width=True)
        st.caption("키 파라미터는 *** 로 마스킹. 헤더 인증(J-Quants x-api-key 등)은 애초에 기록하지 않음.")
        for i, c in enumerate(calls, start=1):
            tag = "캐시" if c.cache_hit else ("실패" if not c.ok else f"HTTP {c.status}")
            with st.expander(f"#{i} · {c.source} · {tag} · {c.url}"):
                if c.params:
                    st.write("요청 파라미터 (키 마스킹)")
                    st.json(c.params)
                st.write("응답 원문 (미리보기)")
                st.code(c.preview or "(빈 응답)")


def _render_report(report, market: str) -> None:
    st.subheader(f"{report.name} ({report.stock_code})")
    st.caption(f"{report.source} · 통화 {report.currency or '—'} · 시세기준 "
               f"{report.asof.isoformat() if report.asof else '—'}")

    metrics = frames.overview_metrics(report)
    cols = st.columns(len(metrics))
    for col, (label, val) in zip(cols, metrics.items()):
        suffix = "%" if "discount" in label else ""
        col.metric(label, "—" if val is None else f"{val:,.1f}{suffix}")

    st.markdown("#### 종합 NAV — 케이스별 range")
    st.dataframe(frames.scenario_frame(report), hide_index=True, use_container_width=True)
    st.caption("S0 보수=전 자산 장부 · S1 추정하한 · S2 추정상한(🔴 검토대기 포함). "
               "nav_discount>0 → NAV 대비 할인(쌈).")

    if report.screen is not None:
        s = report.screen
        st.markdown("#### 1차 스크린 지표")
        c = st.columns(4)
        c[0].metric("PBR", "—" if s.pbr is None else f"{float(s.pbr):.2f}")
        c[1].metric("자기자본비율", "—" if s.equity_ratio is None else f"{float(s.equity_ratio) * 100:.1f}%")
        c[2].metric("PER", "—" if s.per is None else f"{float(s.per):.2f}")
        c[3].metric("창업연도", str(s.founded_year) if s.founded_year else "—")

    for title, intro, df in frames.section_frames(report):
        st.markdown(f"#### {title}")
        if intro:
            st.caption(intro)
        st.dataframe(df, hide_index=True, use_container_width=True)

    if report.catalyst_score is not None:
        trap = " · ⚠️ value-trap 경계" if report.value_trap else ""
        st.info(f"카탈리스트 점수 = {report.catalyst_score}{trap}")

    with st.expander("각주 / 가정"):
        for f in report.footnotes:
            st.markdown(f"- {f}")
    with st.expander("📄 전체 Markdown 리포트 · 다운로드"):
        md = render_markdown(report)
        st.download_button("Markdown 다운로드", md, file_name=f"{report.stock_code}_report.md")
        st.code(md, language="markdown")


# --------------------------------------------------------------------------- #
# Tabs
# --------------------------------------------------------------------------- #
def _tab_report(cfg, market_override, year) -> None:
    st.markdown("단일 종목 NAV 점검 — 1차 스크린 지표 + 케이스별 range + 종목/필지별 섹션 + 신뢰도.")
    code = st.text_input("종목코드", value="000050",
                         help="KR 6자리(000050) / JP 4자리(9031) — 자리수로 자동판별").strip()
    c1, c2 = st.columns(2)
    auto_land = c1.checkbox("투자부동산/賃貸 공정가치 자동추출 (--auto-land)", value=True)
    catalyst = c2.checkbox("카탈리스트 점수 (KR 공시)", value=False)

    if st.button("리포트 실행", type="primary", key="run_report") and code:
        try:
            market = resolve_market([code], market_override)
        except ValueError as exc:
            st.error(str(exc))
            return
        idx = _jp_index(cfg) if market == "jp" else None
        with st.spinner(f"{market.upper()} 리포트 생성 중…"), use_recorder() as rec:
            try:
                pipe = make_pipeline(cfg, market, landprice_index=idx)
                if market == "kr":
                    _ensure_kr_corpcodes(pipe)
                report = build_company_report(
                    pipe, code, bsns_year=year, compute_catalyst=catalyst, auto_land=auto_land,
                )
            except Exception as exc:  # noqa: BLE001 — 사용자에게 원인 표시
                st.error(f"실행 오류: {type(exc).__name__}: {exc}")
                _render_api_log(rec)
                return
        if report is None:
            st.error(f"데이터 없음: {code} ({market.upper()}) — 코드/시장/키를 확인하세요.")
        else:
            _render_report(report, market)
        _render_api_log(rec)


def _tab_screen_value(cfg, market_override, year) -> None:
    st.markdown("여러 종목 1차 자산가치주 스크린 — PBR·자기자본비율·PER·창업연도 필터(✅/✗).")
    codes_raw = st.text_input("종목코드들 (쉼표)", value="000050,000950,004370", key="sv_codes")
    c = st.columns(4)
    pbr = c[0].number_input("PBR 상한", value=0.5, step=0.1, format="%.2f")
    er = c[1].number_input("자기자본비율 하한", value=0.6, step=0.05, format="%.2f")
    per = c[2].number_input("PER 상한 (0=미적용)", value=12.0, step=1.0)
    founded = c[3].number_input("창업≤ (0=미적용)", value=0, step=1)

    if st.button("스크린 실행", type="primary", key="run_sv"):
        codes = [s.strip() for s in codes_raw.split(",") if s.strip()]
        if not codes:
            st.warning("종목코드를 입력하세요.")
            return
        try:
            market = resolve_market(codes, market_override)
        except ValueError as exc:
            st.error(str(exc))
            return
        from decimal import Decimal
        thr: dict = {"pbr_max": Decimal(str(pbr)), "equity_ratio_min": Decimal(str(er))}
        if per > 0:
            thr["per_max"] = Decimal(str(per))
        if founded > 0:
            thr["founded_before"] = int(founded)
        with st.spinner(f"{market.upper()} 스크린 중…"), use_recorder() as rec:
            try:
                pipe = make_pipeline(cfg, market)
                if market == "kr":
                    _ensure_kr_corpcodes(pipe)
                results = value_screen(pipe, codes, bsns_year=year, **thr)
            except Exception as exc:  # noqa: BLE001
                st.error(f"실행 오류: {type(exc).__name__}: {exc}")
                _render_api_log(rec)
                return
        if not results:
            st.error("결과 없음 — 코드/시장/키를 확인하세요.")
        else:
            st.dataframe(frames.screen_value_frame(results), hide_index=True, use_container_width=True)
            n_pass = sum(1 for _, ok in results if ok)
            st.success(f"통과 {n_pass}/{len(results)}")
            if market == "jp":
                st.caption("JP는 창업연도 미공시 → --founded-before 적용 시 전부 탈락(정상).")
        _render_api_log(rec)


def _tab_rank(cfg, market_override, year) -> None:
    st.markdown("여러 종목 NAV_discount 랭킹 — 지분/토지/투자부동산 합산 후 시총 대비 할인율.")
    codes_raw = st.text_input("종목코드들 (쉼표)", value="000050,000950", key="rk_codes")
    catalyst = st.checkbox("카탈리스트 점수 (KR 공시)", value=False, key="rk_cat")

    if st.button("랭킹 실행", type="primary", key="run_rank"):
        codes = [s.strip() for s in codes_raw.split(",") if s.strip()]
        if not codes:
            st.warning("종목코드를 입력하세요.")
            return
        try:
            market = resolve_market(codes, market_override)
        except ValueError as exc:
            st.error(str(exc))
            return
        with st.spinner(f"{market.upper()} NAV 집계 중…"), use_recorder() as rec:
            try:
                pipe = make_pipeline(cfg, market)
                if market == "kr":
                    _ensure_kr_corpcodes(pipe)
                run = pipe.run(stock_codes=codes, bsns_year=year, compute_catalyst=catalyst)
            except Exception as exc:  # noqa: BLE001
                st.error(f"실행 오류: {type(exc).__name__}: {exc}")
                _render_api_log(rec)
                return
        if not run.results:
            st.error("결과 없음 — 코드/시장/키를 확인하세요.")
        else:
            df = results_to_dataframe(run.results)
            st.dataframe(df, hide_index=True, use_container_width=True)
            st.download_button("CSV 다운로드", df.to_csv(index=False),
                               file_name="asset_play_ranking.csv", mime="text/csv")
            if run.quota_exhausted:
                st.warning("DART 쿼터 소진 — 부분 결과입니다.")
            for w in run.warnings[:10]:
                st.caption(f"⚠️ {w}")
        _render_api_log(rec)


def main() -> None:
    st.title("🏢 Asset-Play 숨은자산 스크리너")
    st.caption("상장사 토지·상장주식·지분의 장부가↔시가 괴리(NAV)로 含み資産 종목 발굴 · KR(DART)+JP(EDINET) · "
               "리서치 보조용(투자자문 아님)")
    cfg, market_override, year = _sidebar()
    tab1, tab2, tab3 = st.tabs(["📋 종목 리포트", "🔎 1차 스크린", "🏆 NAV 랭킹"])
    with tab1:
        _tab_report(cfg, market_override, year)
    with tab2:
        _tab_screen_value(cfg, market_override, year)
    with tab3:
        _tab_rank(cfg, market_override, year)


main()
