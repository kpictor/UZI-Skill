"""Public-source contracts and positive/negative execution-gate coverage."""
from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from lib.daily_screen import sources
from lib.daily_screen.execution import execution_gaps
from lib.daily_screen.models import StockSnapshot
from lib.daily_screen.ranker import build_candidate

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 4, 10, 5, tzinfo=TZ)


def snapshot(code="600001.SH", market="A"):
    stock = StockSnapshot(code, "测试股份", market, 10, 5, 2e9, "电子", high=10,
                          turnover_rate=5, market_cap=1e10, observed_at=NOW.isoformat(), source="fixture:quote")
    quote = dict(code=code, currency="HKD" if market == "H" else "CNY", quote_at=NOW.isoformat(),
                 source="fixture:quote", price=10, bid=9.99, ask=10, bid_size=20, ask_size=30,
                 amount=2e9, vwap=9.9, change_pct=5)
    bars = [{"at": (NOW - timedelta(minutes=n)).isoformat(), "close": 10, "amount_local": 3e6}
            for n in (2, 1, 0)]
    stock.extra["intraday"] = {"quote": quote, "bars": bars, "minute_source": "fixture:minute"}
    stock.extra["industry_coverage"] = 1.0
    stock.extra["industry_source"] = {"source": "fixture:classification"}
    return stock


def news():
    return [{"kind": "event", "grade": "C", "title": "测试股份公告", "company_specific": True,
             "source": "fixture:news", "url": "https://example.com/notice",
             "published_at": (NOW - timedelta(hours=1)).isoformat()}]


def tencent_wire(code, market):
    fields = [""] * 40
    values = {1: "测试股份", 2: code, 3: "10", 4: "9.5", 5: "9.6", 6: "20000", 9: "9.99", 10: "20",
              19: "10", 20: "30", 30: "2026/09/04 10:05:00" if market == "hk" else "20260904100500",
              32: "5", 33: "10.1", 34: "9.6", 37: "200000" if market == "hk" else "2000"}
    for key, value in values.items():
        fields[key] = value
    return f'v_{market}{code}="' + "~".join(fields) + '";'


def test_tencent_units_and_exchange_timestamp():
    a = sources.parse_tencent(tencent_wire("600001", "sh"), "600001.SH")
    h = sources.parse_tencent(tencent_wire("00700", "hk"), "00700.HK")
    assert a["amount"] == 20_000_000
    assert a["volume_shares"] == 2_000_000
    assert h["amount"] == 200_000
    assert h["volume_shares"] == 20_000
    assert a["vwap"] == h["vwap"] == 10
    assert a["quote_at"] == h["quote_at"] == NOW.isoformat()


def test_tencent_rejects_different_security_and_invalid_input():
    with pytest.raises(ValueError, match="mismatch"):
        sources.parse_tencent(tencent_wire("600001", "sh"), "600002.SH")
    with pytest.raises(ValueError, match="invalid"):
        sources.parse_tencent("", '600001.SH&other=1')


def test_quote_fallback_keeps_actual_source_and_timestamp(monkeypatch):
    monkeypatch.setattr(sources, "_response", Mock(side_effect=ValueError("upstream")))
    monkeypatch.setattr(sources, "_json", lambda *a: {"data": {
        "f57": "600001", "f86": NOW.timestamp(), "f43": 10, "f19": 9.99,
        "f39": 10, "f20": 2, "f40": 3, "f71": 9.9, "f48": 2e9,
    }})
    quote, errors = sources.fetch_quote(snapshot())
    assert quote["source"] == "eastmoney:quote"
    assert quote["quote_at"] == NOW.isoformat()
    assert errors == ["tencent:ValueError"]


def test_minutes_drop_future_wrong_day_and_bad_rows():
    payload = {"data": {"code": "600001", "trends": [
        "2026-09-04 10:05,10,10,10,10,100,100000,10",
        "2026-09-04 10:06,10,10,10,10,100,100000,10",
        "2026-09-03 10:04,10,10,10,10,100,100000,10",
        "2026-09-04 10:04,10,nan,10,10,100,100000,10",
    ]}}
    bars = sources.parse_minutes(payload, "600001.SH", NOW.isoformat())
    assert len(bars) == 1
    assert bars[0]["amount_local"] == 100000
    with pytest.raises(ValueError, match="mismatch"):
        sources.parse_minutes(payload, "600002.SH", NOW.isoformat())


def test_tencent_minutes_have_explicit_date_and_incremental_amounts():
    payload = {"data": {"sh600001": {"data": {"date": "20260904", "data": [
        "1003 10 10 10000", "1004 10 20 21000", "1005 10 30 33000", "1006 10 40 46000",
    ]}}}}
    bars = sources.parse_tencent_minutes(payload, "600001.SH", NOW.isoformat())
    assert [row["amount_local"] for row in bars] == [10000, 11000, 12000]
    payload["data"]["sh600001"]["data"]["date"] = "20260903"
    assert sources.parse_tencent_minutes(payload, "600001.SH", NOW.isoformat()) == []


def test_intraday_uses_minute_fallback_after_eastmoney_failure(monkeypatch):
    stock = snapshot()
    quote = dict(stock.extra["intraday"]["quote"], change_pct=5)
    monkeypatch.setattr(sources, "fetch_quote", lambda _: (quote, []))
    def get(url, params):
        if url == sources.MINUTES:
            raise ValueError("source unavailable")
        return {"data": {"sh600001": {"data": {"date": "20260904", "data": [
            "1003 10 10 10000", "1004 10 20 21000", "1005 10 30 33000",
        ]}}}}
    monkeypatch.setattr(sources, "_json", get)
    sources.enrich_intraday(stock)
    assert stock.extra["intraday"]["minute_source"] == "tencent:minute"
    assert len(stock.extra["intraday"]["bars"]) == 3


def test_industry_batch_maps_by_code_not_response_order(monkeypatch):
    stocks = [snapshot(), snapshot("000001.SZ")]
    monkeypatch.setattr(sources, "cached", lambda ticker, key, fn, ttl: fn())
    params_seen = []
    def get(url, params):
        params_seen.append(params)
        return {"success": True, "result": {"pages": 1, "data": [
            {"SECUCODE": "000001.SZ", "EM2016": "金融-银行"},
            {"SECUCODE": "600001.SH", "EM2016": "电子-芯片"},
            {"SECUCODE": "600999.SH", "EM2016": "unexpected"},
        ]}}
    monkeypatch.setattr(sources, "_json", get)
    health = sources.fetch_industries(stocks)
    assert stocks[0].industry == "电子-芯片"
    assert stocks[1].industry == "金融-银行"
    assert health["A"]["covered"] == 2
    assert '"600001.SH"' in params_seen[0]["filter"]
    assert stocks[0].extra["industry_source"]["field"] == "EM2016"


def test_failed_industry_does_not_fabricate_classification(monkeypatch):
    stock = snapshot()
    stock.industry = "未分类"
    monkeypatch.setattr(sources, "cached", lambda ticker, key, fn, ttl: fn())
    monkeypatch.setattr(sources, "_json", Mock(side_effect=ValueError("incomplete")))
    assert sources.fetch_industries([stock])["A"]["covered"] == 0
    assert stock.industry == "未分类"


def test_positive_gate_can_leave_watch_only(monkeypatch):
    monkeypatch.setattr("lib.daily_screen.execution.exchange_open", lambda *a: True)
    stock = snapshot()
    assert execution_gaps(stock, NOW) == []
    pick = build_candidate(stock, {"theme_rank": 1, "leader_rank": 1, "breadth_pct": 100, "observed_at": NOW.isoformat()}, news(), [], evaluated_at=NOW)
    assert pick.action == "buyable"
    assert "intraday_execution_unverified" not in pick.data_gaps


@pytest.mark.parametrize("change,expected", [
    ({"quote_at": (NOW - timedelta(minutes=15)).isoformat()}, "quote_stale_or_future"),
    ({"quote_at": (NOW + timedelta(seconds=1)).isoformat()}, "quote_stale_or_future"),
    ({"ask_size": 0}, "book_or_vwap_missing"),
    ({"vwap": None}, "book_or_vwap_missing"),
    ({"currency": "USD"}, "quote_identity_mismatch"),
    ({"ask": 10.2}, "book_spread_excessive"),
    ({"bid": 1, "ask": 1.001}, "book_quote_price_mismatch"),
    ({"vwap": 11}, "vwap_support_unconfirmed"),
])
def test_bad_quote_never_releases_execution(monkeypatch, change, expected):
    monkeypatch.setattr("lib.daily_screen.execution.exchange_open", lambda *a: True)
    stock = snapshot()
    stock.extra["intraday"]["quote"].update(change)
    assert expected in execution_gaps(stock, NOW)
    assert build_candidate(stock, {"theme_rank": 1, "leader_rank": 1, "breadth_pct": 100}, news(), [], evaluated_at=NOW).action == "watch_only"


def test_hk_missing_book_and_closed_exchange_are_observation_only(monkeypatch):
    monkeypatch.setattr("lib.daily_screen.execution.exchange_open", lambda *a: False)
    stock = snapshot("00700.HK", "H")
    stock.extra["intraday"]["quote"]["ask_size"] = 0
    gaps = execution_gaps(stock, NOW)
    assert "book_or_vwap_missing" in gaps
    assert "exchange_closed_or_unverified" in gaps


@pytest.mark.parametrize("field,value", [("amount", 3e9), ("change_pct", None), ("source", "other")])
def test_mixed_snapshot_cannot_pass(monkeypatch, field, value):
    monkeypatch.setattr("lib.daily_screen.execution.exchange_open", lambda *a: True)
    stock = snapshot()
    stock.extra["intraday"]["quote"][field] = value
    assert "snapshot_quote_mismatch" in execution_gaps(stock, NOW)


@pytest.mark.parametrize("field,value,expected", [
    ("at", (NOW - timedelta(hours=1)).isoformat(), "minute_sequence_unverified"),
    ("at", "invalid", "minute_liquidity_unverified"),
    ("amount_local", float("nan"), "minute_liquidity_unverified"),
    ("amount_local", 0, "minute_liquidity_unverified"),
])
def test_incomplete_recent_minutes_cannot_pass(monkeypatch, field, value, expected):
    monkeypatch.setattr("lib.daily_screen.execution.exchange_open", lambda *a: True)
    stock = snapshot()
    stock.extra["intraday"]["bars"][0][field] = value
    assert expected in execution_gaps(stock, NOW)


def test_missing_news_url_or_relevance_blocks_even_with_good_tape(monkeypatch):
    monkeypatch.setattr("lib.daily_screen.execution.exchange_open", lambda *a: True)
    for key, value in (("url", ""), ("company_specific", False), ("published_at", "2025-01-01")):
        evidence = news()
        evidence[0][key] = value
        pick = build_candidate(snapshot(), {"theme_rank": 1, "leader_rank": 1, "breadth_pct": 100}, evidence, [], evaluated_at=NOW)
        assert pick.action == "watch_only"


def test_events_use_structured_news_instead_of_display_timeline(monkeypatch):
    from lib.daily_screen.events import enrich_stock
    import fetch_events
    import fetch_lhb
    monkeypatch.setattr(fetch_events, "main", lambda _: {"data": {
        "event_timeline": ["2026-09-04 · 展示摘要"], "recent_news": [{
            "title": "测试股份：业务公告", "date": "2026-09-04 10:00:00",
            "url": "https://example.com/news", "source": "fixture",
        }],
    }})
    monkeypatch.setattr(fetch_lhb, "main", lambda _: {})
    evidence, gaps = enrich_stock(snapshot())
    assert not gaps
    assert evidence[0]["company_specific"] is True
    assert evidence[0]["url"] == "https://example.com/news"
    assert evidence[0]["published_at"] == "2026-09-04 10:00:00"


@pytest.mark.parametrize("age,expected", [(0, "buyable"), (200, "watch_only")])
def test_runner_wires_sources_and_rechecks_quote_age_at_publication(monkeypatch, tmp_path, age, expected):
    from lib.daily_screen import runner
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    stocks = [snapshot(), snapshot("600002.SH")]
    for stock in stocks:
        stock.extra["intraday"]["quote"]["quote_at"] = (NOW - timedelta(seconds=age)).isoformat()
    monkeypatch.setattr(runner, "datetime", Clock)
    monkeypatch.setattr(runner, "fetch_market_universe", lambda _: stocks)
    industry = Mock(return_value={"A": {"coverage": 1.0}})
    intraday = Mock()
    monkeypatch.setattr(runner, "fetch_industries", industry)
    monkeypatch.setattr(runner, "enrich_intraday", intraday)
    monkeypatch.setattr(runner, "enrich_stock", lambda _: (news(), []))
    monkeypatch.setattr("lib.daily_screen.execution.exchange_open", lambda *a: True)
    report = runner.run_daily_screen(markets=("A",), enrich=True, track=False, output_root=tmp_path)
    assert report["picks"][0]["action"] == expected
    assert report["data_quality"]["intraday_available"] == 2
    industry.assert_called_once()
    assert intraday.call_count == 2


def test_runner_reapplies_user_turnover_floor_after_quote_refresh(monkeypatch, tmp_path):
    from lib.daily_screen import runner
    stock = snapshot()
    monkeypatch.setattr(runner, "fetch_market_universe", lambda _: [stock])
    monkeypatch.setattr(runner, "fetch_industries", lambda _: {})
    monkeypatch.setattr(runner, "enrich_stock", lambda _: ([], []))
    monkeypatch.setattr(runner, "enrich_intraday", lambda item: setattr(item, "amount", 3e8))
    report = runner.run_daily_screen(markets=("A",), min_turnover_local=5e8,
                                     track=False, output_root=tmp_path)
    assert report["picks"] == []
    assert report["data_quality"]["removed_after_quote_refresh"] == 1
