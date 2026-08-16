"""The decision contract: the ONLY thing the model may return.

Structural validation lives here (shape, ranges, duplicates). Semantic validation against the
mandate (whitelist, sleeve caps, cash, cooldowns, never-widen stops) lives in risk.py — the model's
output is untrusted input either way. The model never sees or emits order quantities.

Semantics:
  action == "rebalance":  `positions` is the COMPLETE desired trend+spec book. Any held active
                          position not listed is exited. Core is never in `positions`.
  action == "no_change":  keep the current book; only `stop_updates` (tighten-only) are applied.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ibagent.common import ActiveSleeve, RunType

MAX_ACTIVE_POSITIONS = 12
_MAX_ACTIVE_WEIGHT_STRUCTURAL = 1.0  # semantic cap (trend+spec weights) enforced in risk.py


class DecisionError(ValueError):
    """Raised when raw model output does not satisfy the contract."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _norm_symbol(s: str) -> str:
    return s.strip().upper()


class PositionIntent(_Model):
    symbol: str = Field(min_length=1, max_length=12, description="Whitelisted ticker")
    sleeve: ActiveSleeve
    target_weight: float = Field(ge=0, le=0.5, description="Fraction of pot equity for this position")
    thesis: str = Field(min_length=10, max_length=400)
    invalidation: str = Field(min_length=5, max_length=300, description="What would prove the thesis wrong")
    stop_price: Optional[float] = Field(default=None, gt=0,
                                        description="Initial protective stop; engine may tighten, never widen")
    target_price: Optional[float] = Field(default=None, gt=0)
    confidence: float = Field(ge=0, le=1)
    horizon_days: int = Field(ge=1, le=180)

    @model_validator(mode="after")
    def _check(self) -> "PositionIntent":
        self.symbol = _norm_symbol(self.symbol)
        if self.stop_price is not None and self.target_price is not None and self.stop_price >= self.target_price:
            raise ValueError(f"{self.symbol}: stop_price must be below target_price")
        return self


class StopUpdate(_Model):
    symbol: str = Field(min_length=1, max_length=12)
    stop_price: float = Field(gt=0, description="New stop; engine applies only if tighter than current")
    reason: str = Field(min_length=3, max_length=200)

    @model_validator(mode="after")
    def _check(self) -> "StopUpdate":
        self.symbol = _norm_symbol(self.symbol)
        return self


class Decision(_Model):
    schema_version: Literal[1] = 1
    run_type: RunType
    action: Literal["no_change", "rebalance"]
    market_regime: Literal["risk_on", "neutral", "risk_off"]
    risk_multiplier: float = Field(ge=0, le=1, description="Scales trend+spec exposure; 1.0 = full mandate")
    positions: List[PositionIntent] = Field(default_factory=list, max_length=MAX_ACTIVE_POSITIONS,
                                            description="Complete desired trend+spec book (rebalance only)")
    stop_updates: List[StopUpdate] = Field(default_factory=list, max_length=MAX_ACTIVE_POSITIONS)
    watchlist: List[str] = Field(default_factory=list, max_length=15,
                                 description="Symbols the news gate should watch for event triggers")
    notes_for_human: str = Field(max_length=1200)
    journal_lessons: str = Field(default="", max_length=800,
                                 description="Self-review of recent decisions vs outcomes")

    @model_validator(mode="after")
    def _check(self) -> "Decision":
        syms = [p.symbol for p in self.positions]
        if len(set(syms)) != len(syms):
            raise ValueError("duplicate symbols in positions")
        if self.action == "no_change" and self.positions:
            raise ValueError("action=no_change must not carry positions; use stop_updates or action=rebalance")
        total = sum(p.target_weight for p in self.positions)
        if total > _MAX_ACTIVE_WEIGHT_STRUCTURAL + 1e-9:
            raise ValueError(f"active target weights sum to {total:.3f} > 1.0")
        upd = [u.symbol for u in self.stop_updates]
        if len(set(upd)) != len(upd):
            raise ValueError("duplicate symbols in stop_updates")
        self.watchlist = sorted({_norm_symbol(w) for w in self.watchlist if w.strip()})
        return self

    @property
    def total_active_weight(self) -> float:
        return sum(p.target_weight for p in self.positions)


def decision_json_schema() -> Dict[str, Any]:
    """JSON Schema handed to `claude -p --json-schema` (structured output)."""
    return Decision.model_json_schema()


def decision_json_schema_text() -> str:
    return json.dumps(decision_json_schema(), separators=(",", ":"))


def parse_decision(raw: Any, expected_run_type: Optional[RunType] = None) -> Decision:
    """Validate raw model output. Raises DecisionError with a message suitable for a retry prompt."""
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DecisionError(f"output is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise DecisionError("output must be a JSON object")
    try:
        d = Decision.model_validate(raw)
    except ValidationError as exc:
        raise DecisionError(_format_validation_error(exc)) from exc
    if expected_run_type and d.run_type != expected_run_type:
        raise DecisionError(f"run_type must be '{expected_run_type}', got '{d.run_type}'")
    return d


def hold_decision(run_type: RunType, reason: str) -> Decision:
    """The engine's fallback when the model is unavailable or keeps violating the contract."""
    return Decision(run_type=run_type, action="no_change", market_regime="neutral", risk_multiplier=1.0,
                    notes_for_human=f"HOLD (engine fallback): {reason}"[:1200])


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", ())) or "<root>"
        lines.append(f"{loc}: {e.get('msg')}")
    return "; ".join(lines)
