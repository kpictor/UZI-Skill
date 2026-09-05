"""Observable execution prerequisites, not a promise of a future fill."""
from datetime import datetime

from lib.cache import market_status
from .events import evidence_time
from .models import StockSnapshot
from .universe import _number


def exchange_open(market: str, now: datetime) -> bool:
    try:
        import exchange_calendars as xcals
        import pandas as pd
        calendar = xcals.get_calendar("XHKG" if market == "H" else "XSHG")
        return bool(calendar.is_open_on_minute(pd.Timestamp(now).floor("min"), ignore_breaks=False)) and market_status(market, now)["is_open"]
    except (ImportError, ValueError, TypeError, AttributeError):
        return False


def execution_gaps(stock: StockSnapshot, now: datetime) -> list[str]:
    bundle = stock.extra.get("intraday") or {}
    quote, bars = bundle.get("quote") or {}, bundle.get("bars") or []
    if not quote or not bars:
        return ["intraday_execution_unverified"]
    gaps = []
    if not quote.get("source") or not bundle.get("minute_source"):
        gaps.append("intraday_source_unverified")
    at = evidence_time(quote.get("quote_at"))
    if at is None or not 0 <= (now - at).total_seconds() <= 120:
        gaps.append("quote_stale_or_future")
    if not exchange_open(stock.market, now):
        gaps.append("exchange_closed_or_unverified")
    if quote.get("code") != stock.code or quote.get("currency") != ("HKD" if stock.market == "H" else "CNY"):
        gaps.append("quote_identity_mismatch")
    if (_number(quote.get("change_pct")) is None
            or evidence_time(stock.observed_at) != at
            or stock.source != quote.get("source")):
        gaps.append("snapshot_quote_mismatch")
    required = ("price", "bid", "ask", "bid_size", "ask_size", "amount", "vwap")
    if any(_number(quote.get(key)) is None or _number(quote.get(key)) <= 0 for key in required):
        gaps.append("book_or_vwap_missing")
    else:
        price, bid, ask, vwap = (float(quote[key]) for key in ("price", "bid", "ask", "vwap"))
        if ask < bid or (ask - bid) / price > 0.005:
            gaps.append("book_spread_excessive")
        if abs(ask / price - 1) > 0.01 or abs(bid / price - 1) > 0.01:
            gaps.append("book_quote_price_mismatch")
        if (abs(stock.price / price - 1) > 0.001 or stock.amount < 2e8
                or abs(stock.amount / float(quote["amount"]) - 1) > 0.001):
            gaps.append("snapshot_quote_mismatch")
        if not vwap <= price <= vwap * 1.03:
            gaps.append("vwap_support_unconfirmed")
    last = bars[-1]
    last_at = evidence_time(last.get("at"))
    if at is None or last_at is None or not 0 <= (at - last_at).total_seconds() <= 120:
        gaps.append("minute_quote_time_mismatch")
    recent = bars[-3:]
    stamps = [evidence_time(row.get("at")) for row in recent]
    amounts = [_number(row.get("amount_local")) for row in recent]
    if (len(recent) < 3 or any(stamp is None for stamp in stamps)
            or any(amount is None or amount <= 0 for amount in amounts)):
        gaps.append("minute_liquidity_unverified")
    elif any((right - left).total_seconds() != 60 for left, right in zip(stamps, stamps[1:])):
        gaps.append("minute_sequence_unverified")
    price, close = _number(quote.get("price")), _number(last.get("close"))
    if not price or not close or abs(close / price - 1) > 0.01:
        gaps.append("minute_quote_price_mismatch")
    return sorted(set(gaps))
