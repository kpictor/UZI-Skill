"""Cross-market trading clock regression tests."""
from __future__ import annotations

import sys
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))


def test_market_status_uses_each_exchange_timezone_and_sessions():
    from lib.cache import market_status

    instant = datetime(2026, 8, 28, 2, 0, tzinfo=timezone.utc)
    a = market_status("A", instant)
    hk = market_status("H", instant)
    us = market_status("U", instant)

    assert a["is_open"] is True
    assert hk["is_open"] is True
    assert us["is_open"] is False
    assert a["timezone"] == "Asia/Shanghai"
    assert us["timezone"] == "America/New_York"


def test_market_status_handles_hk_lunch_break():
    from lib.cache import market_status

    instant = datetime(2026, 8, 28, 4, 30, tzinfo=timezone.utc)
    status = market_status("H", instant)
    assert status["is_open"] is False
    assert status["label"] == "午间休市"


def test_market_status_rejects_weekends():
    from lib.cache import market_status

    status = market_status("U", datetime(2026, 8, 29, 15, 0, tzinfo=timezone.utc))
    assert status["is_open"] is False


def test_market_status_uses_exchange_calendar_holiday(monkeypatch):
    from lib.cache import market_status

    fake_calendar = SimpleNamespace(is_session=lambda _date: False)
    monkeypatch.setitem(sys.modules, "exchange_calendars", SimpleNamespace(get_calendar=lambda _name: fake_calendar))
    status = market_status("A", datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc))
    assert status["is_open"] is False
    assert status["label"] == "已休市 (非交易日)"
    assert status["calendar_verified"] is True
