"""End-to-end orchestration for the A/H daily screen."""
from __future__ import annotations

import json
import math
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from .events import enrich_stock
from .events import evidence_time
from .models import StockSnapshot
from .ranker import build_candidate, preselect, rank_candidates
from .renderer import render_report
from .themes import build_theme_context
from .tracker import append_signals
from .universe import apply_hard_filters, fetch_market_universe
from .sources import enrich_intraday, fetch_industries


def _enrich_candidate(stock: StockSnapshot):
    evidence, gaps = enrich_stock(stock)
    try:
        enrich_intraday(stock)
    except Exception as exc:
        gaps.append(f"intraday:{type(exc).__name__}")
    return evidence, gaps


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _cutoff(now: datetime, market: str, mode: str) -> str:
    if mode == "noon":
        target = time(11, 30) if market == "A" else time(12, 0)
    else:
        target = time(15, 0) if market == "A" else time(16, 0)
    cutoff = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    if now < cutoff:
        cutoff = now
    return cutoff.isoformat(timespec="seconds")


def run_daily_screen(
    mode: str = "noon",
    markets: tuple[str, ...] = ("A", "H"),
    top_n: int = 10,
    min_turnover_local: float = 2e8,
    enrich: bool = True,
    track: bool = True,
    output_root: Path | None = None,
    now: datetime | None = None,
    frozen_stocks: list[StockSnapshot] | None = None,
) -> dict:
    if mode not in ("noon", "close"):
        raise ValueError("mode must be noon or close")
    if not 1 <= top_n <= 10:
        raise ValueError("top_n must be between 1 and 10")
    if not math.isfinite(min_turnover_local) or min_turnover_local < 2e8:
        raise ValueError("minimum turnover must be finite and at least 200 million")
    if now is not None and frozen_stocks is None:
        raise ValueError("historical/as-of runs require frozen_stocks; live quotes cannot be backdated")
    if frozen_stocks is not None and enrich:
        raise ValueError("frozen snapshots must not be enriched with live news; use enrich=False")
    tz = ZoneInfo("Asia/Shanghai")
    now = now.astimezone(tz) if now and now.tzinfo else (now.replace(tzinfo=tz) if now else datetime.now(tz))
    markets = tuple(dict.fromkeys(item.strip().upper() for item in markets if item.strip()))
    if not markets or any(item not in ("A", "H") for item in markets):
        raise ValueError("markets only supports A,H")

    all_stocks = []
    theme_universe = []
    universe_stats = {}
    market_errors = {}
    as_of_by_market = {}
    for market in markets:
        try:
            if frozen_stocks is None:
                fetched = fetch_market_universe(market)
            else:
                boundary = evidence_time(_cutoff(now, market, mode))
                fetched = [stock for stock in frozen_stocks if stock.market == market
                           and evidence_time(stock.observed_at) is not None
                           and evidence_time(stock.observed_at) <= boundary]
            timestamps = [evidence_time(stock.observed_at) for stock in fetched]
            if not fetched or any(stamp is None for stamp in timestamps):
                raise ValueError("market snapshot is empty or lacks observation timestamps")
            as_of_by_market[market] = max(timestamps).isoformat(timespec="seconds")
            theme_universe.extend(fetched)
            filtered, stats = apply_hard_filters(fetched, min_turnover_local)
            all_stocks.extend(filtered)
            universe_stats[market] = stats
        except Exception as exc:
            market_errors[market] = f"{type(exc).__name__}: {str(exc)[:160]}"
            universe_stats[market] = {"input": 0, "liquid": 0, "error": market_errors[market]}

    industry_health = fetch_industries(theme_universe) if enrich and frozen_stocks is None else {}
    shortlisted = preselect(all_stocks, limit=40)
    enrichments: dict[str, tuple[list[dict], list[str]]] = {
        stock.code: ([], ["snapshot_only"]) for stock in shortlisted
    }
    if enrich and shortlisted:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_enrich_candidate, stock): stock.code for stock in shortlisted}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    enrichments[code] = future.result()
                except Exception as exc:
                    enrichments[code] = ([], [f"enrichment:{type(exc).__name__}"])

    # Evaluate freshness once, after all source work; slow peers cannot leave a
    # previously accepted quote marked executable at publication time.
    generated_at = datetime.now(tz)
    shortlisted, refreshed_filter_stats = apply_hard_filters(shortlisted, min_turnover_local)
    themes = build_theme_context(theme_universe)
    for market in as_of_by_market:
        stamps = [evidence_time(stock.observed_at) for stock in theme_universe if stock.market == market]
        as_of_by_market[market] = max(stamp for stamp in stamps if stamp is not None).isoformat(timespec="seconds")
    candidates = []
    for stock in shortlisted:
        evidence, gaps = enrichments[stock.code]
        candidates.append(build_candidate(stock, themes.get(stock.code, {}), evidence, gaps, evaluated_at=generated_at))
    picks, rejected = rank_candidates(candidates, top_n=top_n)
    action_summary = Counter(item.action for item in picks)

    report_id = f"{generated_at:%Y%m%d}-{mode}-ah-{generated_at:%H%M%S%f}"
    scripts_root = Path(__file__).resolve().parents[2]
    output_root = output_root or scripts_root / "reports" / "screens" / generated_at.strftime("%Y-%m-%d") / report_id
    report = {
        "report_id": report_id,
        "mode": mode,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "as_of_by_market": as_of_by_market,
        "snapshot_kind": "frozen" if frozen_stocks is not None else "live",
        "analysis_basis": "rule_only",
        "filters": {
            "exclude_st": True,
            "exclude_suspended": True,
            "min_turnover_local": min_turnover_local,
            "top_n": top_n,
            "min_research_confidence": 70,
        },
        "universe_stats": universe_stats,
        "market_errors": market_errors,
        "action_summary": dict(action_summary),
        "picks": [item.to_dict() for item in picks],
        "rejected": [item.to_dict() for item in rejected[:20]],
        "data_quality": {
            "markets_requested": list(markets),
            "markets_available": [market for market in markets if market not in market_errors],
            "enrichment_enabled": enrich,
            "shortlisted": len(shortlisted),
            "removed_after_quote_refresh": refreshed_filter_stats["removed_low_turnover"],
            "industry_sources": industry_health,
            "intraday_available": sum(bool(stock.extra.get("intraday", {}).get("bars")) for stock in shortlisted),
        },
        "performance_contract": {
            "entry": "first_executable_price_after_publish",
            "horizons": ["close", "next_open", "next_close", "3d"],
            "status": "paper_trading",
        },
    }
    _atomic_json(output_root / "picks.json", report)
    _atomic_json(output_root / "report.meta.json", {
        "report_id": report_id,
        "generated_at": report["generated_at"],
        "picks_count": len(picks),
        "markets": list(markets),
        "html": "index.html",
    })
    avatars = Path(__file__).resolve().parents[3] / "assets" / "avatars"
    html_path = render_report(report, output_root / "index.html", avatars)
    if track:
        append_signals(scripts_root / ".cache" / "_daily_screen" / "signals.jsonl", report)
    report["report_path"] = str(html_path)
    return report
