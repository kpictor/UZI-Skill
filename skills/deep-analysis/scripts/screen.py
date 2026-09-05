#!/usr/bin/env python3
"""CLI for the auditable A/H daily screen."""
from __future__ import annotations

import argparse
import json
import webbrowser
from pathlib import Path

from lib.daily_screen import run_daily_screen


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="UZI A+港股每日游资/Serenity 筛选")
    parser.add_argument("--mode", choices=("noon", "close"), default="noon")
    parser.add_argument("--markets", default="A,H", help="逗号分隔，仅支持 A,H")
    parser.add_argument("--schools", default="F,I", help="当前固定 F,I；保留参数用于兼容")
    parser.add_argument("--top", type=int, default=10, help="候选上限，1-10，不是配额")
    parser.add_argument("--min-turnover", type=float, default=2e8, help="每市场本币最低实际成交额")
    parser.add_argument("--snapshot-only", action="store_true", help="跳过逐股消息/历史龙虎榜增强")
    parser.add_argument("--no-track", action="store_true", help="不追加 paper-trading 账本")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    schools = {item.strip().upper() for item in args.schools.split(",") if item.strip()}
    if schools != {"F", "I"}:
        parser.error("daily screen 当前要求 --schools F,I")
    result = run_daily_screen(
        mode=args.mode,
        markets=tuple(item.strip().upper() for item in args.markets.split(",") if item.strip()),
        top_n=args.top,
        min_turnover_local=args.min_turnover,
        enrich=not args.snapshot_only,
        track=not args.no_track,
        output_root=args.output,
    )
    print(json.dumps({
        "report_id": result["report_id"],
        "picks": len(result["picks"]),
        "report_path": result["report_path"],
        "market_errors": result["market_errors"],
    }, ensure_ascii=False, indent=2))
    if not args.no_browser:
        webbrowser.open(Path(result["report_path"]).resolve().as_uri())
    return result


if __name__ == "__main__":
    main()
