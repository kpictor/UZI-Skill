"""Offline regression probes for report and daily-screen audit findings."""
from datetime import datetime
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from lib.daily_screen.models import StockSnapshot


def stock(code="600001.SH", market="A", industry="电子", stamp="2026-09-04T14:00:00+08:00"):
    return StockSnapshot(code, "测试半导体", market, 10, 5, 2e9,
                         industry=industry, high=10, turnover_rate=5,
                         market_cap=10e9, observed_at=stamp, source="fixture")


def test_stage2_reaches_rendering_without_global_cache_root(monkeypatch, tmp_path):
    import run_real_test as rrt
    import lib.cache as cache
    import assemble_report
    import inline_assets
    import render_share_card
    import render_war_report

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UZI_DEPTH", "medium")
    monkeypatch.setenv("UZI_NO_AUTO_OPEN", "1")
    monkeypatch.setattr(cache, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(rrt, "_resolve_cached_target", lambda *a, **kw: SimpleNamespace(full="TEST"))
    monkeypatch.setattr(cache, "read_task_output", lambda *a: {"fixture": True})
    monkeypatch.setattr(rrt, "write_task_output", Mock())
    monkeypatch.setattr(rrt, "generate_synthesis", lambda *a, **kw: {"overall_score": 50, "verdict_label": "fixture"})
    report = tmp_path / "fixture.html"
    report.write_text("<!doctype html><p>" + "fixture " * 2000 + "</p>")
    assemble = Mock(return_value=report)
    monkeypatch.setattr(assemble_report, "assemble", assemble)
    monkeypatch.setattr(inline_assets, "main", lambda _: report)
    monkeypatch.setattr(render_share_card, "main", Mock())
    monkeypatch.setattr(render_war_report, "main", Mock())
    assert rrt.stage2("TEST") == str(report)
    assemble.assert_called_once_with("TEST")


def test_stage2_enforces_persisted_deep_gate(monkeypatch, tmp_path):
    import run_real_test as rrt
    import lib.cache as cache

    monkeypatch.delenv("UZI_DEPTH", raising=False)
    monkeypatch.setattr(cache, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(rrt, "_resolve_cached_target", lambda *a, **kw: SimpleNamespace(full="TEST"))
    monkeypatch.setattr(cache, "read_task_output", lambda *a: {"fixture": True})
    (tmp_path / "TEST").mkdir()
    (tmp_path / "TEST" / "_agent_review_context.json").write_text('{"depth":"deep"}')
    with pytest.raises(RuntimeError, match="HARD-GATE"):
        rrt.stage2("TEST")


def test_live_noon_report_keeps_actual_afternoon_timestamp(monkeypatch, tmp_path):
    from lib.daily_screen.runner import run_daily_screen
    monkeypatch.setattr("lib.daily_screen.runner.fetch_market_universe", lambda _: [stock(), stock("600002.SH")])
    report = run_daily_screen(markets=("A",), enrich=False, track=False, output_root=tmp_path)
    assert report["as_of_by_market"]["A"] == "2026-09-04T14:00:00+08:00"
    assert report["analysis_basis"] == "rule_only"
    assert all(pick["action"] == "watch_only" for pick in report["picks"])


def test_historical_run_cannot_fetch_live_quotes(monkeypatch, tmp_path):
    from lib.daily_screen.runner import run_daily_screen
    fetch = Mock(side_effect=AssertionError("must not fetch"))
    monkeypatch.setattr("lib.daily_screen.runner.fetch_market_universe", fetch)
    with pytest.raises(ValueError, match="frozen_stocks"):
        run_daily_screen(now=datetime(2026, 9, 4, 11, 30), output_root=tmp_path)
    fetch.assert_not_called()


def test_frozen_noon_excludes_afternoon_snapshot(monkeypatch, tmp_path):
    from lib.daily_screen.runner import run_daily_screen
    monkeypatch.setattr("lib.daily_screen.runner.fetch_market_universe", Mock(side_effect=AssertionError("live")))
    report = run_daily_screen(markets=("A",), now=datetime(2026, 9, 4, 14),
                              frozen_stocks=[stock()], enrich=False, track=False, output_root=tmp_path)
    assert report["picks"] == []
    assert "A" in report["market_errors"]
    with pytest.raises(ValueError, match="live news"):
        run_daily_screen(frozen_stocks=[stock()], enrich=True)


def test_events_exclude_future_unknown_and_same_day_date_only(monkeypatch):
    from lib.daily_screen.events import enrich_stock
    import fetch_events
    import fetch_lhb
    monkeypatch.setattr(fetch_events, "main", lambda _: {"data": {"event_timeline": [
        {"title": "未来公告", "date": "2026-09-07"},
        {"title": "日期缺失"},
        {"title": "当日时刻未知", "date": "2026-09-04"},
        {"title": "已知时刻公告", "date": "2026-09-04T10:00:00+08:00"},
    ]}})
    monkeypatch.setattr(fetch_lhb, "main", lambda _: {"data": {"lhb_records": [
        {"date": "2026-09-03"}, {"date": "2026-09-04"}, {"date": ""},
    ]}})
    evidence, gaps = enrich_stock(stock())
    assert len(evidence) == 2
    assert evidence[0]["grade"] == "C"
    assert evidence[1]["kind"] == "lhb"
    assert "evidence_time_unverified" in gaps


def test_no_evidence_never_becomes_buyable_and_does_not_mutate_gaps():
    from lib.daily_screen.ranker import build_candidate
    gaps = ["snapshot_only"]
    pick = build_candidate(stock(), {"theme_rank": 1, "leader_rank": 1, "breadth_pct": 100}, [], gaps)
    assert pick.research_confidence >= 70
    assert pick.action == "watch_only"
    assert "event_evidence_missing" in pick.data_gaps
    assert "intraday_execution_unverified" in pick.data_gaps
    assert gaps == ["snapshot_only"]


@pytest.mark.parametrize("code", ["600001.SH", "300001.SZ", "688001.SH", "920001.BJ"])
def test_change_pct_alone_does_not_prove_unbuyable(code):
    from lib.daily_screen.ranker import build_candidate
    snapshot = stock(code)
    snapshot.change_pct = 10
    assert build_candidate(snapshot, {}, [], []).action == "watch_only"


def test_real_spot_columns_without_industry_do_not_form_theme():
    from lib.daily_screen.universe import normalize_universe_frame
    from lib.daily_screen.themes import build_theme_context
    frame = pd.DataFrame([{"代码": code, "名称": "测试", "最新价": 10, "涨跌幅": 5, "成交额": 2e9}
                          for code in ("600001", "600002")])
    snapshots = normalize_universe_frame(frame, "A", stock().observed_at, "fixture")
    assert build_theme_context(snapshots) == {}


def test_themes_are_separate_by_market():
    from lib.daily_screen.themes import build_theme_context
    stocks = [stock(), stock("600002.SH"), stock("00001.HK", "H"), stock("00002.HK", "H")]
    stocks[2].change_pct = stocks[3].change_pct = -2
    themes = build_theme_context(stocks)
    assert themes["600001.SH"]["breadth_pct"] == 100
    assert themes["00001.HK"]["breadth_pct"] == 0
    assert themes["600001.SH"]["theme_rank"] == themes["00001.HK"]["theme_rank"] == 1


def test_theme_breadth_uses_full_universe_before_liquidity_filter(monkeypatch, tmp_path):
    from lib.daily_screen.runner import run_daily_screen
    stocks = [stock(), stock("600002.SH")]
    stocks[1].amount, stocks[1].change_pct = 1e7, -2
    monkeypatch.setattr("lib.daily_screen.runner.fetch_market_universe", lambda _: stocks)
    report = run_daily_screen(markets=("A",), enrich=False, track=False, output_root=tmp_path)
    candidates = report["picks"] + report["rejected"]
    assert candidates[0]["theme_breadth_pct"] == 50


def test_serenity_requires_verified_business_fact_not_lhb_or_title():
    from lib.daily_screen.personas import evaluate_serenity
    lhb = {"kind": "lhb", "grade": "B", "published_at": "2026-09-03"}
    headline = {"kind": "event", "grade": "B", "title": "公告", "published_at": "2026-09-03"}
    assert evaluate_serenity(stock(), {}, [lhb]).signal == "neutral"
    assert evaluate_serenity(stock(), {}, [headline]).signal == "neutral"
    fact = dict(headline, business_fact_verified=True, business_fact="production",
                url="https://example.com/filing", source="fixture")
    assert evaluate_serenity(stock(), {}, [fact]).signal == "bullish"
    fact["published_at"] = "2026-09-07"
    assert evaluate_serenity(stock(), {}, [fact]).signal == "neutral"


def test_raw_dump_keys_and_nested_values_are_html_text():
    from assemble_report import render_dim_card
    payload = "</pre><img src=x onerror=alert(1)>"
    rendered = render_dim_card("1_financials", {"score": 5}, {"data": {payload: {payload: payload}}})
    tags = []
    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append((tag, attrs))
    Parser().feed(rendered)
    assert not any(tag == "img" for tag, _ in tags)
    assert "&lt;img" in rendered


def test_bad_url_does_not_crash_renderer():
    from lib.report.security import safe_url
    assert safe_url("https://[invalid") == "#"


@pytest.mark.parametrize("profit, margin", [(0, 0), (-20, -20), (20, 20)])
def test_financials_keep_zero_and_negative_ttm(profit, margin):
    from lib.stock_features import extract_features
    fin = {"revenue_ttm": 100, "net_profit_ttm": profit, "net_profit_history": [50]}
    f = extract_features({"dimensions": {"1_financials": {"data": fin}}}, {})
    assert f["net_profit_latest_yi"] == profit
    assert f["net_margin"] == margin
    assert f["net_margin_basis"] == "ttm"


def test_partial_ttm_does_not_mix_margin_periods():
    from lib.stock_features import extract_features
    fin = {"revenue_ttm": 100, "net_profit_history": [20]}
    def features():
        return extract_features({"dimensions": {"1_financials": {"data": fin}}}, {})
    assert features()["net_margin"] is None
    fin["revenue_history"] = [200]
    assert features()["net_margin"] == 10
    assert features()["net_margin_basis"] == "annual"


@pytest.mark.parametrize("code, expected", [("920001", "920001.BJ"), ("830799", "830799.BJ"),
                                           ("430001", "430001.BJ"), ("600001", "600001.SH"),
                                           ("300001", "300001.SZ"), ("00700", "00700.HK")])
def test_stock_code_exchange_mapping(code, expected):
    from lib.daily_screen.universe import _full_code
    assert _full_code(code, "H" if expected.endswith("HK") else "A") == expected


@pytest.mark.parametrize("value", [float("inf"), float("nan"), -1, 1e8])
def test_invalid_minimum_turnover_rejected_before_network(value):
    from lib.daily_screen.runner import run_daily_screen
    with pytest.raises(ValueError, match="turnover"):
        run_daily_screen(min_turnover_local=value)
