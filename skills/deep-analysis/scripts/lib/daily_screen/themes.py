"""Cross-sectional theme strength derived from the same observable snapshot."""
from __future__ import annotations

from collections import defaultdict

from .models import StockSnapshot
from .events import evidence_time


def build_theme_context(stocks: list[StockSnapshot]) -> dict[str, dict]:
    groups: dict[tuple[str, str], list[StockSnapshot]] = defaultdict(list)
    for stock in stocks:
        industry = stock.industry.strip()
        if industry.lower() in ("", "未分类", "未知", "—", "nan", "none"):
            continue
        groups[(stock.market, industry)].append(stock)
    rows = []
    for (market, industry), members in groups.items():
        if len(members) < 2:
            continue
        rows.append({
            "market": market,
            "industry": industry,
            "avg_change_pct": sum(item.change_pct for item in members) / len(members),
            "breadth_pct": sum(1 for item in members if item.change_pct > 0) / len(members) * 100,
            "amount": sum(item.amount for item in members),
            "members": sorted(members, key=lambda item: (item.change_pct, item.amount), reverse=True),
            "observed_at": min((evidence_time(item.observed_at) for item in members
                                if evidence_time(item.observed_at) is not None), default=None),
        })
    rows.sort(key=lambda row: (row["avg_change_pct"], row["breadth_pct"], row["amount"]), reverse=True)
    context: dict[str, dict] = {}
    market_ranks: dict[str, int] = defaultdict(int)
    for row in rows:
        market_ranks[row["market"]] += 1
        theme_rank = market_ranks[row["market"]]
        for leader_rank, stock in enumerate(row["members"], 1):
            context[stock.code] = {
                "theme_rank": theme_rank,
                "leader_rank": leader_rank,
                "breadth_pct": round(row["breadth_pct"], 1),
                "theme_avg_change_pct": round(row["avg_change_pct"], 2),
                "theme_amount": row["amount"],
                "observed_at": row["observed_at"].isoformat() if row["observed_at"] is not None else None,
                "sample_size": len(row["members"]),
            }
    return context
