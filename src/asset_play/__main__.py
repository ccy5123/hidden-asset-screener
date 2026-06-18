"""Command-line interface: ``asset-play sync-corp-codes`` / ``asset-play screen``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from .config import Config
from .domain.enums import Market


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no python-dotenv dependency). Does not override real env."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


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
    from .pipeline import Pipeline

    config = Config.from_env()
    if args.universe:
        try:
            config.universe = Market(args.universe.upper())
        except ValueError:
            print(f"unknown universe: {args.universe}", file=sys.stderr)
            return 2

    pipe = Pipeline(config)
    stock_codes = _split(args.stock)
    corp_codes = _split(args.corp)

    if not stock_codes and not corp_codes and args.all:
        rows = pipe.cache.get_json("dart:corpcode", "all") or pipe.sync_corp_codes()
        stock_codes = [r["stock_code"] for r in rows if r.get("stock_code")]
        print(f"[--all] screening {len(stock_codes)} listed names (DART quota heavy)…")

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
    )
    print(f"ranked {len(run.results)} companies")
    if run.quota_exhausted:
        print("⚠️ DART quota exhausted — results are partial", file=sys.stderr)
    for w in run.warnings[:10]:
        print(f"  warn: {w}", file=sys.stderr)
    print(f"CSV  → {csv_path}")
    print(f"HTML → {html_path}")
    return 0


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
    screen.add_argument("--out", default="out", help="출력 디렉터리 (기본: out)")
    screen.set_defaults(func=_cmd_screen)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    _load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
