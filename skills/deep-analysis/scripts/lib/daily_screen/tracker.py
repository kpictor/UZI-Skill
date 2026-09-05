"""Append-only paper-trading signal ledger."""
from __future__ import annotations

import json
import os
from pathlib import Path


def append_signals(path: Path, report: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for pick in report.get("picks", []):
        lines.append(json.dumps({
            "report_id": report.get("report_id"),
            "generated_at": report.get("generated_at"),
            "performance_contract": report.get("performance_contract"),
            "signal": pick,
        }, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
    if not lines:
        return 0
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, "".join(lines).encode("utf-8"))
    finally:
        os.close(fd)
    return len(lines)
