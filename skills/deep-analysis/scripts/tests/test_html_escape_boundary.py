"""Report output encoding and URL allow-list regression tests."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))


PAYLOAD = '<img src=x onerror="alert(1)">'


def test_institutional_renderers_escape_agent_and_upstream_text():
    from lib.report.institutional import _render_catalyst_calendar, _render_ic_memo

    catalyst = _render_catalyst_calendar({"catalyst_calendar": {"events": [{"date": "2026-01-01", "event": PAYLOAD}]}})
    memo = _render_ic_memo({"ic_memo": {"sections": {
        "I_exec_summary": {"headline": PAYLOAD},
        "VII_returns_scenarios": [],
        "VI_risks_mitigants": [],
    }}})

    assert PAYLOAD not in catalyst
    assert "&lt;img" in catalyst
    assert PAYLOAD not in memo
    assert "&lt;img" in memo


def test_panel_renderer_escapes_roleplay_text_and_asset_id():
    from lib.report.panel_cards import render_chat_message

    rendered = render_chat_message({
        "investor_id": "../../evil\" onerror=alert(1)",
        "name": PAYLOAD,
        "reasoning": PAYLOAD,
        "signal": "neutral",
    })
    assert PAYLOAD not in rendered
    assert "../" not in rendered
    assert "&lt;img" in rendered


def test_special_renderer_rejects_javascript_urls():
    from lib.report.special_cards import render_friendly_layer

    rendered = render_friendly_layer({"friendly": {"similar_stocks": [{
        "name": "测试",
        "code": "TEST",
        "url": "javascript:alert(1)",
    }]}}, {})
    assert 'href="#"' in rendered
    assert "javascript:" not in rendered
