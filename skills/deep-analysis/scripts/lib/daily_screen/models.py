"""Typed contracts for immutable daily-screen snapshots."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StockSnapshot:
    code: str
    name: str
    market: str
    price: float
    change_pct: float
    amount: float
    industry: str = "未分类"
    open_price: float | None = None
    prev_close: float | None = None
    high: float | None = None
    low: float | None = None
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    market_cap: float | None = None
    observed_at: str = ""
    source: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PersonaVerdict:
    investor_id: str
    name: str
    style: str
    eligible: bool
    signal: str
    confidence: int
    matched_patterns: list[str]
    vetoes: list[str]
    reasoning_summary: str
    entry_condition: str
    invalidation: str
    horizon: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScreenCandidate:
    snapshot: StockSnapshot
    research_confidence: float
    action: str
    why_now: str
    entry_condition: str
    invalidation: str
    theme_rank: int | None
    leader_rank: int | None
    theme_breadth_pct: float | None
    persona_verdicts: list[PersonaVerdict] = field(default_factory=list)
    serenity: PersonaVerdict | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["snapshot"] = self.snapshot.to_dict()
        result["persona_verdicts"] = [item.to_dict() for item in self.persona_verdicts]
        result["serenity"] = self.serenity.to_dict() if self.serenity else None
        return result
