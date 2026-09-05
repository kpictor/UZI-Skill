"""Freshness contract between collected evidence and agent role-play output."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTEXT_FILE = "_agent_review_context.json"


def requires_agent_review(cache_dir: Path) -> bool:
    if os.environ.get("UZI_DEPTH") == "deep":
        return True
    try:
        context = json.loads((cache_dir / CONTEXT_FILE).read_text(encoding="utf-8"))
        return isinstance(context, dict) and context.get("depth") == "deep"
    except (OSError, ValueError):
        return False


def analysis_input_hash(raw: dict[str, Any]) -> str:
    payload = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_review_context(cache_dir: Path, raw: dict[str, Any]) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    context = {
        "ticker": raw.get("full") or raw.get("ticker"),
        "analysis_input_hash": analysis_input_hash(raw),
        "raw_fetched_at": raw.get("fetched_at"),
        "depth": os.environ.get("UZI_DEPTH", "medium"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    target = cache_dir / CONTEXT_FILE
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return context


def load_fresh_agent_analysis(cache_dir: Path, raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    analysis_path = cache_dir / "agent_analysis.json"
    raw_path = cache_dir / "raw_data.json"
    if not analysis_path.exists():
        return None, "agent_analysis.json 缺失"
    try:
        payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"agent_analysis.json 无法读取: {type(exc).__name__}"
    if not isinstance(payload, dict) or payload.get("agent_reviewed") is not True:
        return None, "agent_reviewed 未设置为 true"

    current_hash = analysis_input_hash(raw)
    declared_hash = payload.get("analysis_input_hash")
    if declared_hash:
        if declared_hash != current_hash:
            return None, "analysis_input_hash 与当前 raw_data 不一致"
        return payload, "fingerprint matched"

    if requires_agent_review(cache_dir):
        return None, "deep 档必须提供 analysis_input_hash"

    try:
        if raw_path.exists() and analysis_path.stat().st_mtime_ns < raw_path.stat().st_mtime_ns:
            return None, "agent_analysis.json 早于当前 raw_data"
    except OSError as exc:
        return None, f"无法校验分析时间: {type(exc).__name__}"
    return payload, "mtime matched (legacy analysis without fingerprint)"
