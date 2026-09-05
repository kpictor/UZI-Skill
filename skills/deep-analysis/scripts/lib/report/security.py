"""Output-encoding helpers for report renderers."""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse


_ASSET_ID = re.compile(r"[^A-Za-z0-9_-]+")


def escape_text(value: Any) -> str:
    """HTML-escape text idempotently so nested renderers may call it safely."""
    return html.escape(html.unescape(str(value)), quote=True)


def escape_payload(value: Any) -> Any:
    if isinstance(value, str):
        return escape_text(value)
    if isinstance(value, dict):
        return {key: escape_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [escape_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(escape_payload(item) for item in value)
    return value


def safe_url(value: Any, default: str = "#") -> str:
    raw = html.unescape(str(value or "")).strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return default
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return default
    return escape_text(raw)


def safe_asset_id(value: Any, default: str = "_placeholder") -> str:
    cleaned = _ASSET_ID.sub("", str(value or ""))[:80]
    return cleaned or default
