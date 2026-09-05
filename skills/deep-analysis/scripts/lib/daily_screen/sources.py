"""Bounded public-data adapters; source timestamps are never retrieval times."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from lib.cache import cached, TTL_QUARTERLY
from .events import evidence_time
from .models import StockSnapshot
from .universe import _number

TZ = ZoneInfo("Asia/Shanghai")
DATACENTER = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
QUOTE = "https://push2.eastmoney.com/api/qt/stock/get"
MINUTES = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
CODE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$|^(\d{5})\.HK$")


def _code_parts(code: str) -> tuple[str, str]:
    if not CODE.fullmatch(code):
        raise ValueError("invalid A/H security code")
    return tuple(code.split("."))


def _response(url: str, params: dict | None = None):
    response = requests.get(url, params=params, timeout=(3, 8),
                            headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200 or len(response.content) > 2_000_000:
        raise ValueError("unexpected public-data response")
    return response


def _json(url: str, params: dict) -> dict:
    payload = _response(url, params).json()
    if not isinstance(payload, dict):
        raise ValueError("expected object response")
    return payload


def fetch_industries(stocks: list[StockSnapshot]) -> dict:
    """Batch current-universe identifiers, cache successful batches for one day."""
    health = {}
    by_code = {stock.code: stock for stock in stocks}
    for market, report, field in (("A", "RPT_F10_BASIC_ORGINFO", "EM2016"),
                                   ("H", "RPT_HKF10_INFO_ORGPROFILE", "BELONG_INDUSTRY")):
        codes = sorted(stock.code for stock in stocks if stock.market == market)
        if not codes:
            continue
        for code in codes:
            _code_parts(code)
        covered_codes, errors = set(), []
        for offset in range(0, len(codes), 200):
            batch = codes[offset:offset + 200]
            def fetch_batch():
                payload = _json(DATACENTER, {
                    "reportName": report, "columns": f"SECUCODE,{field}",
                    "filter": '(SECUCODE in (' + ','.join(json.dumps(code) for code in batch) + '))',
                    "pageNumber": 1, "pageSize": 500, "source": "F10", "client": "PC",
                })
                result = payload.get("result") or {}
                if not payload.get("success") or result.get("pages") != 1:
                    raise ValueError("industry batch incomplete")
                rows = result.get("data") or []
                if not rows:
                    raise ValueError("empty industry batch")
                return {"rows": rows, "observed_at": datetime.now(TZ).isoformat(timespec="seconds")}
            try:
                data = cached("_daily_screen", "industry:" + market + ",".join(batch), fetch_batch, TTL_QUARTERLY)
                for row in data["rows"]:
                    code, industry = row.get("SECUCODE"), str(row.get(field) or "").strip()
                    if code not in batch or not industry or industry in ("-", "--", "未分类"):
                        continue
                    by_code[code].industry = industry
                    by_code[code].extra["industry_source"] = {
                        "source": f"eastmoney:{report}", "field": field,
                        "observed_at": data["observed_at"], "classification": "current_not_historical",
                    }
                    covered_codes.add(code)
            except Exception as exc:
                errors.append(type(exc).__name__)
                # Do not issue dozens of identical requests during a source outage.
                break
        coverage = len(covered_codes) / len(codes)
        for code in codes:
            by_code[code].extra["industry_coverage"] = coverage
        health[market] = {"requested": len(codes), "covered": len(covered_codes), "coverage": coverage, "errors": errors}
    return health


def parse_tencent(text: str, code: str) -> dict:
    raw, exchange = _code_parts(code)
    symbol = exchange.lower() + raw
    match = re.search(r'v_' + re.escape(symbol) + r'="([^"\r\n]+)";', text)
    if match is None:
        raise ValueError("Tencent security mismatch")
    fields = match.group(1).split("~")
    if len(fields) < 38 or fields[2] != raw:
        raise ValueError("Tencent quote schema mismatch")
    stamp = fields[30]
    try:
        at = datetime.strptime(stamp, "%Y%m%d%H%M%S" if exchange != "HK" else "%Y/%m/%d %H:%M:%S").replace(tzinfo=TZ)
    except ValueError as exc:
        raise ValueError("Tencent quote timestamp missing") from exc
    def number(index):
        return _number(fields[index])
    lot_multiplier = 1 if exchange == "HK" else 100
    amount = number(37)
    amount = amount * (1 if exchange == "HK" else 10000) if amount is not None else None
    volume = number(6)
    volume = volume * lot_multiplier if volume is not None else None
    quote = {
        "code": code, "source": "tencent:qt", "quote_at": at.isoformat(timespec="seconds"),
        "price": number(3), "prev_close": number(4), "open_price": number(5),
        "change_pct": number(32), "high": number(33), "low": number(34),
        "amount": amount, "volume_shares": volume,
        "bid": number(9), "ask": number(19),
        "bid_size": number(10), "ask_size": number(20),
        "book_size_unit": "provider_lots" if exchange != "HK" else "provider_units",
        "currency": "HKD" if exchange == "HK" else "CNY",
        "vwap": amount / volume if amount is not None and volume and volume > 0 else None,
    }
    return quote


def fetch_quote(stock: StockSnapshot) -> tuple[dict, list[str]]:
    raw, exchange = _code_parts(stock.code)
    errors = []
    partial = {}
    try:
        quote = parse_tencent(_response(f"https://qt.gtimg.cn/q={exchange.lower()}{raw}").content.decode("gbk"), stock.code)
        partial = quote
        if all(quote.get(field) is not None and quote[field] > 0 for field in ("price", "bid", "ask", "ask_size", "bid_size")):
            return quote, errors
        errors.append("tencent:book_missing")
    except Exception as exc:
        errors.append(f"tencent:{type(exc).__name__}")
    try:
        secid = f"{'116' if exchange == 'HK' else '1' if exchange == 'SH' else '0'}.{raw}"
        data = _json(QUOTE, {"secid": secid, "fltt": 2, "invt": 2,
                            "fields": "f57,f58,f43,f44,f45,f46,f48,f60,f71,f86,f170,f19,f20,f39,f40"}).get("data") or {}
        if str(data.get("f57")) != raw or not _number(data.get("f86")):
            raise ValueError("EastMoney quote identity/time missing")
        quote = {key: _number(data.get(field)) for key, field in {
            "price": "f43", "prev_close": "f60", "open_price": "f46", "high": "f44", "low": "f45",
            "amount": "f48", "change_pct": "f170", "vwap": "f71",
            "bid": "f19", "bid_size": "f20", "ask": "f39", "ask_size": "f40",
        }.items()}
        quote.update(code=stock.code, source="eastmoney:quote", currency="HKD" if exchange == "HK" else "CNY",
                     book_size_unit="provider_units", quote_at=datetime.fromtimestamp(float(data["f86"]), TZ).isoformat(timespec="seconds"))
        return quote, errors
    except Exception as exc:
        errors.append(f"eastmoney_quote:{type(exc).__name__}")
    return partial, errors


def parse_minutes(payload: dict, code: str, cutoff: str) -> list[dict]:
    raw, _ = _code_parts(code)
    data = payload.get("data") or {}
    if str(data.get("code")) != raw:
        raise ValueError("minute security mismatch")
    boundary = evidence_time(cutoff)
    if boundary is None:
        raise ValueError("minute cutoff missing")
    bars = {}
    for row in csv.reader(data.get("trends") or []):
        if len(row) != 8:
            continue
        stamp = evidence_time(row[0])
        close, amount = _number(row[2]), _number(row[6])
        if (stamp is None or stamp.date() != boundary.date() or stamp > boundary
                or close is None or close <= 0 or amount is None or amount < 0):
            continue
        bars[stamp] = {"at": stamp.isoformat(timespec="seconds"), "close": close, "amount_local": amount}
    return [bars[at] for at in sorted(bars)]


def parse_tencent_minutes(payload: dict, code: str, cutoff: str) -> list[dict]:
    raw, exchange = _code_parts(code)
    data = ((payload.get("data") or {}).get(exchange.lower() + raw) or {}).get("data") or {}
    day = datetime.strptime(str(data.get("date")), "%Y%m%d").date()
    rows, previous_amount = [], 0.0
    for item in data.get("data") or []:
        fields = item.split()
        if len(fields) != 4:
            raise ValueError("Tencent minute schema mismatch")
        clock = datetime.strptime(fields[0], "%H%M").time()
        amount = _number(fields[3])
        if amount is None or amount < previous_amount:
            raise ValueError("Tencent cumulative amount invalid")
        # Tencent minute amounts are cumulative; EastMoney minute amounts are not.
        delta = amount - previous_amount
        previous_amount = amount
        stamp = datetime.combine(day, clock).strftime("%Y-%m-%d %H:%M")
        rows.append(f"{stamp},0,{fields[1]},0,0,0,{delta},0")
    return parse_minutes({"data": {"code": raw, "trends": rows}}, code, cutoff)


def enrich_intraday(stock: StockSnapshot) -> None:
    quote, errors = fetch_quote(stock)
    stock.extra["intraday"] = {"quote": quote, "bars": [], "source_errors": errors}
    if not quote:
        return
    # Keep the latest quote atomic: no old spot price mixed with new book/amount.
    if all(quote.get(field) is not None for field in ("price", "amount", "change_pct")) and quote["price"] > 0:
        for field in ("price", "amount", "change_pct", "prev_close", "open_price", "high", "low"):
            setattr(stock, field, quote.get(field))
        stock.observed_at = quote["quote_at"]
        stock.source = quote["source"]
    raw, exchange = _code_parts(stock.code)
    try:
        payload = _json(MINUTES, {
            "secid": f"{'116' if exchange == 'HK' else '1' if exchange == 'SH' else '0'}.{raw}",
            "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58", "ndays": 1, "iscr": 0,
        })
        stock.extra["intraday"].update(bars=parse_minutes(payload, stock.code, quote["quote_at"]),
                                      minute_source="eastmoney:trends2")
    except Exception as exc:
        errors.append(f"eastmoney_minutes:{type(exc).__name__}")
    if len(stock.extra["intraday"]["bars"]) < 3:
        try:
            payload = _json("https://web.ifzq.gtimg.cn/appstock/app/minute/query", {"code": exchange.lower() + raw})
            bars = parse_tencent_minutes(payload, stock.code, quote["quote_at"])
            if len(bars) > len(stock.extra["intraday"]["bars"]):
                stock.extra["intraday"].update(bars=bars, minute_source="tencent:minute")
        except Exception as exc:
            errors.append(f"tencent_minutes:{type(exc).__name__}")
