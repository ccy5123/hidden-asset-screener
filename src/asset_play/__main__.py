"""Command-line interface: ``asset-play sync-corp-codes`` / ``asset-play screen``."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .config import Config
from .domain.enums import Market
from .exceptions import SourceError
from .market import detect_market, make_pipeline, resolve_market  # noqa: F401 (re-export for tests)


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no python-dotenv dependency). Does not override real env.

    Tolerant of an optional ``export`` prefix and surrounding single/double quotes, so
    ``KEY=abc``, ``KEY="abc"`` and ``export KEY='abc'`` all yield the same value.
    """
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]  # strip matching surrounding quotes
        if key:
            os.environ.setdefault(key, value)


def _split(value: Optional[str]) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _cmd_sync(args: argparse.Namespace) -> int:
    from .pipeline import Pipeline

    pipe = Pipeline(Config.from_env())
    rows = pipe.sync_corp_codes()
    listed = sum(1 for r in rows if r.get("stock_code"))
    print(f"synced {len(rows)} corp codes ({listed} listed) → cache {pipe.cache.path}")
    return 0


def _cmd_screen(args: argparse.Namespace) -> int:
    config = Config.from_env()
    if args.universe:
        try:
            config.universe = Market(args.universe.upper())
        except ValueError:
            print(f"unknown universe: {args.universe}", file=sys.stderr)
            return 2

    stock_codes = _split(args.stock)
    corp_codes = _split(args.corp)
    # 시장 판별(KR 6자리 / JP 4자리) — corp_code(8자리)는 KR로 판정됨. 섞이면 거부.
    market = resolve_market(stock_codes, getattr(args, "market", None))
    pipe = make_pipeline(config, market, extra_landprice=getattr(args, "landprice_files", None))

    if not stock_codes and not corp_codes and args.all:
        rows = pipe.cache.get_json("dart:corpcode", "all") or pipe.sync_corp_codes()
        stock_codes = [r["stock_code"] for r in rows if r.get("stock_code")]
        print(f"[--all] screening {len(stock_codes)} listed names (DART quota heavy)…")

    # Tier-2 land (human-in-loop): each resolved code is also added to the screen set,
    # so `screen --land-file land.json` is self-sufficient.
    land_by_corp: dict[str, list] = {}
    if args.land_file:
        from .land_file import load_land_assets

        for code, assets in load_land_assets(args.land_file).items():
            cc = code if len(code) == 8 else None
            if cc is None:
                try:
                    cc = pipe.adapter.corp_code_for_stock(code)
                except SourceError:
                    cc = None
            if not cc:
                print(
                    f"  warn: land-file code {code} unresolved (run sync-corp-codes first)",
                    file=sys.stderr,
                )
                continue
            land_by_corp.setdefault(cc, []).extend(assets)
            if len(code) == 8:
                if code not in corp_codes:
                    corp_codes.append(code)
            elif code not in stock_codes:
                stock_codes.append(code)

    if not stock_codes and not corp_codes:
        print(
            "nothing to screen: pass --stock 000270,003550 (or --corp ...) or --all",
            file=sys.stderr,
        )
        return 2

    run, csv_path, html_path = pipe.run_and_report(
        out_dir=args.out,
        stock_codes=stock_codes,
        corp_codes=corp_codes,
        bsns_year=args.year,
        land_assets_by_corp=land_by_corp,
        compute_catalyst=args.catalyst,
    )
    print(f"ranked {len(run.results)} companies")
    if run.quota_exhausted:
        print("⚠️ DART quota exhausted — results are partial", file=sys.stderr)
    for w in run.warnings[:10]:
        print(f"  warn: {w}", file=sys.stderr)
    print(f"CSV  → {csv_path}")
    print(f"HTML → {html_path}")

    if run.unresolved:
        print(
            f"\n비상장 분류 {len(run.unresolved)}건 — 상장 매칭 실패 가능성 점검 (장부가순 상위):",
            file=sys.stderr,
        )
        for name, book, holder in run.unresolved[:15]:
            print(f"  - {name}  (장부 {int(book) / 1e8:,.0f}억, 보유: {holder})", file=sys.stderr)
        upath = Path(args.out)
        upath.mkdir(parents=True, exist_ok=True)
        upath = upath / "unresolved_names.csv"
        with upath.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["investee_name", "book_value_won", "holder"])
            for name, book, holder in run.unresolved:
                w.writerow([name, int(book), holder])
        print(
            f"  → {upath} (상장사인데 누락됐으면 data/name_aliases.json 에 추가)",
            file=sys.stderr,
        )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from .report.markdown_report import build_company_report, write_markdown

    config = Config.from_env()
    market = resolve_market([args.stock], getattr(args, "market", None))
    pipe = make_pipeline(config, market, extra_landprice=getattr(args, "landprice_files", None))
    land_by_corp: dict = {}
    if args.land_file:
        from .land_file import load_land_assets

        for code, assets in load_land_assets(args.land_file).items():
            cc = code if len(code) == 8 else None
            if cc is None:
                try:
                    cc = pipe.adapter.corp_code_for_stock(code)
                except SourceError:
                    cc = None
            if cc:
                land_by_corp.setdefault(cc, []).extend(assets)

    report = build_company_report(
        pipe, args.stock, bsns_year=args.year,
        compute_catalyst=args.catalyst, land_assets_by_corp=land_by_corp or None,
        auto_land=args.auto_land,
    )
    if report is None:
        print(f"no data for {args.stock}", file=sys.stderr)
        return 2
    path = write_markdown(report, Path(args.out) / f"{report.stock_code}_report.md")
    print(f"report → {path}")

    if getattr(args, "review", False):
        from .report.review import claude_review

        rev = claude_review(path, model=args.review_model)
        if rev:
            rpath = path.with_name(f"{path.stem}_review.md")
            rpath.write_text(
                f"# 검수 (Claude) — {report.name} ({report.stock_code})\n\n{rev}\n",
                encoding="utf-8",
            )
            print(f"검수 → {rpath}")
        else:
            print("검수 건너뜀 (claude CLI 미발견 또는 실패)", file=sys.stderr)
    return 0


def _cmd_screen_value(args: argparse.Namespace) -> int:
    from .valuation.screen import value_screen

    stock_codes = _split(args.stock)
    if not stock_codes:
        print("pass --stock 000050,001130,...", file=sys.stderr)
        return 2
    market = resolve_market(stock_codes, getattr(args, "market", None))
    pipe = make_pipeline(Config.from_env(), market)
    thr = dict(pbr_max=Decimal(str(args.pbr)), equity_ratio_min=Decimal(str(args.equity_ratio)))
    if args.per is not None:
        thr["per_max"] = Decimal(str(args.per))
    if args.founded_before is not None:
        thr["founded_before"] = args.founded_before
    results = value_screen(pipe, stock_codes, bsns_year=args.year, **thr)

    def f2(x):
        return "—" if x is None else f"{float(x):.2f}"

    def fp(x):
        return "—" if x is None else f"{float(x) * 100:.0f}%"

    print(f"{'종목':<12}{'PBR':>7}{'자기자본':>9}{'PER':>8}{'창업':>7}  통과")
    print("-" * 50)
    n_pass = 0
    for m, ok in results:
        n_pass += int(ok)
        print(f"{m.name:<12}{f2(m.pbr):>7}{fp(m.equity_ratio):>9}{f2(m.per):>8}"
              f"{str(m.founded_year or '—'):>7}  {'✅' if ok else ''}")
    print(f"\n통과 {n_pass}/{len(results)} "
          f"(PBR≤{args.pbr} · 자기자본비율≥{args.equity_ratio:.0%}"
          f"{f' · PER≤{args.per}' if args.per else ''}"
          f"{f' · 창업≤{args.founded_before}' if args.founded_before else ''})")
    return 0


def _add_market_args(p: argparse.ArgumentParser) -> None:
    """JP 멀티마켓 공통 플래그 — 시장 강제 + 公示地価 GeoJSON 경로(영업용 토지 추정용)."""
    p.add_argument("--market", help="시장 강제 지정 kr|jp (기본: 종목코드 자리수로 자동판별)")
    p.add_argument(
        "--landprice-file",
        dest="landprice_files",
        action="append",
        help="(JP) 国土数値情報 L01/L02 GeoJSON 경로 — 반복 지정 가능. "
        "ASSET_PLAY_LANDPRICE_FILES 환경변수와 병합. 없으면 영업용 토지 추정 생략.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asset-play", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync-corp-codes", help="DART corpCode ↔ stock_code 매핑 동기화").set_defaults(
        func=_cmd_sync
    )

    screen = sub.add_parser("screen", help="지분 NAV 스크리닝 → CSV/HTML 리포트")
    screen.add_argument("--stock", help="쉼표구분 종목코드 (예: 000270,003550)")
    screen.add_argument("--corp", help="쉼표구분 corp_code")
    screen.add_argument("--all", action="store_true", help="전체 상장 유니버스 (쿼터 주의)")
    screen.add_argument("--year", help="사업연도 (기본: 작년)")
    screen.add_argument("--universe", help="KOSPI|KOSDAQ|KONEX|ALL")
    screen.add_argument(
        "--land-file",
        dest="land_file",
        help="토지 자산 파일 (.json/.csv) — 검토된 투자부동산/토지 값 주입 (human-in-loop)",
    )
    screen.add_argument(
        "--catalyst",
        action="store_true",
        help="카탈리스트 점수 산출 (밸류업·자사주·배당 공시 검색, 종목당 DART 호출 +1)",
    )
    screen.add_argument("--out", default="out", help="출력 디렉터리 (기본: out)")
    _add_market_args(screen)
    screen.set_defaults(func=_cmd_screen)

    report = sub.add_parser("report", help="종목별 자산가치 점검 Markdown 보고서 (range + 신뢰도)")
    report.add_argument("--stock", required=True, help="종목코드 (예: 000050)")
    report.add_argument("--year", help="사업연도 (기본: 작년)")
    report.add_argument("--land-file", dest="land_file", help="토지 자산 파일 (.json/.csv)")
    report.add_argument(
        "--auto-land",
        dest="auto_land",
        action="store_true",
        help="투자부동산 토지 자동추출 (별도 공정가치 주석, BS 단위대사) — 수작업 land-file 불필요",
    )
    report.add_argument("--catalyst", action="store_true", help="카탈리스트 점수 포함")
    report.add_argument("--out", default="out", help="출력 디렉터리 (기본: out)")
    report.add_argument(
        "--review",
        action="store_true",
        help="생성 후 Claude로 적대적 검수 (기본 off; claude CLI 필요) → 별도 _review.md",
    )
    report.add_argument(
        "--review-model",
        dest="review_model",
        help="검수 모델 (옵션, 예: opus); 미지정 시 claude CLI 기본값",
    )
    _add_market_args(report)
    report.set_defaults(func=_cmd_report)

    sv = sub.add_parser("screen-value", help="자산가치주 1차 스크린 (PBR·자기자본비율·PER·창업연도)")
    sv.add_argument("--stock", required=True, help="쉼표구분 종목코드")
    sv.add_argument("--pbr", type=float, default=0.5, help="PBR 상한 (기본 0.5)")
    sv.add_argument("--equity-ratio", dest="equity_ratio", type=float, default=0.6,
                    help="자기자본비율 하한 (기본 0.6)")
    sv.add_argument("--per", type=float, help="PER 상한 (옵션, 수익성)")
    sv.add_argument("--founded-before", dest="founded_before", type=int,
                    help="창업연도 상한 (옵션, 오래된 회사)")
    sv.add_argument("--year", help="사업연도 (기본: 작년)")
    sv.add_argument("--market", help="시장 강제 지정 kr|jp (기본: 종목코드 자리수로 자동판별)")
    sv.set_defaults(func=_cmd_screen_value)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    _load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:  # 시장 판별 실패 등 사용자 입력 오류 → 종료코드 2
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
