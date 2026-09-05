"""Agent review fingerprint and stale-analysis regression tests."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))


def test_fingerprint_accepts_matching_agent_analysis(tmp_path):
    from lib.agent_review import analysis_input_hash, load_fresh_agent_analysis

    raw = {"ticker": "TEST", "dimensions": {"0_basic": {"data": {"price": 10}}}}
    (tmp_path / "raw_data.json").write_text(json.dumps(raw), encoding="utf-8")
    payload = {
        "agent_reviewed": True,
        "analysis_input_hash": analysis_input_hash(raw),
        "dim_commentary": {"0_basic": "reviewed"},
    }
    (tmp_path / "agent_analysis.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded, reason = load_fresh_agent_analysis(tmp_path, raw)
    assert loaded == payload
    assert reason == "fingerprint matched"


def test_fingerprint_rejects_stale_agent_analysis(tmp_path):
    from lib.agent_review import analysis_input_hash, load_fresh_agent_analysis

    old_raw = {"ticker": "TEST", "price": 9}
    new_raw = {"ticker": "TEST", "price": 10}
    payload = {"agent_reviewed": True, "analysis_input_hash": analysis_input_hash(old_raw)}
    (tmp_path / "agent_analysis.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded, reason = load_fresh_agent_analysis(tmp_path, new_raw)
    assert loaded is None
    assert "不一致" in reason


def test_legacy_analysis_must_not_predate_raw_snapshot(tmp_path):
    from lib.agent_review import load_fresh_agent_analysis

    analysis = tmp_path / "agent_analysis.json"
    raw_path = tmp_path / "raw_data.json"
    analysis.write_text(json.dumps({"agent_reviewed": True}), encoding="utf-8")
    raw_path.write_text("{}", encoding="utf-8")
    os.utime(analysis, ns=(1_000_000_000, 1_000_000_000))
    os.utime(raw_path, ns=(2_000_000_000, 2_000_000_000))

    loaded, reason = load_fresh_agent_analysis(tmp_path, {})
    assert loaded is None
    assert "早于" in reason


def test_deep_context_survives_new_process_without_depth_env(tmp_path, monkeypatch):
    from lib.agent_review import load_fresh_agent_analysis, requires_agent_review

    monkeypatch.delenv("UZI_DEPTH", raising=False)
    (tmp_path / "_agent_review_context.json").write_text(json.dumps({"depth": "deep"}))
    (tmp_path / "agent_analysis.json").write_text(json.dumps({"agent_reviewed": True}))
    assert requires_agent_review(tmp_path)
    loaded, reason = load_fresh_agent_analysis(tmp_path, {})
    assert loaded is None
    assert "analysis_input_hash" in reason
