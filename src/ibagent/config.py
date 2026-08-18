"""Mandate loading, validation and capital-scaled sizing.

The mandate is the single source of truth for every limit. It is validated on load and the
engine refuses to start on an invalid mandate. Nothing in here is ever written by the model.

Sizing helpers turn *fractions of current pot equity* plus the absolute USD floors into concrete
numbers, so the same mandate works for a $500 pot and a $50,000 pot:

    max_positions(sleeve) = min(sleeve.max_positions, floor(sleeve_equity / min_position_usd))
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ibagent.common import ActiveSleeve, RunType, Sleeve

READ_ONLY_TOOLS: frozenset = frozenset({"Read", "Grep", "Glob", "WebSearch", "WebFetch"})
PAPER_PORTS: frozenset = frozenset({4002, 7497})
LIVE_PORTS: frozenset = frozenset({4001, 7496})
ACTIVE_SLEEVES: tuple = ("trend", "spec")
ALL_SLEEVES: tuple = ("core", "trend", "spec")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class MandateError(ValueError):
    """Raised for any invalid mandate."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_keys(d: Dict[str, Any], keys: tuple, where: str) -> None:
    missing = [k for k in keys if k not in d]
    extra = [k for k in d if k not in keys]
    if missing or extra:
        raise ValueError(f"{where}: expected exactly keys {list(keys)}, missing={missing}, extra={extra}")


# ----------------------------------------------------------------------------- capital / account


class CapitalCfg(Strict):
    seed_usd: float = Field(gt=0)
    min_operating_equity_usd: float = Field(gt=0)
    min_position_usd: float = Field(gt=0)
    min_order_usd: float = Field(gt=0)
    max_fee_pct_per_trade: float = Field(gt=0, le=5)
    commission_model: Literal["tiered", "fixed", "lite"] = "tiered"

    @model_validator(mode="after")
    def _floors(self) -> "CapitalCfg":
        if self.min_order_usd > self.min_position_usd:
            raise ValueError("capital.min_order_usd must be <= min_position_usd")
        if self.min_operating_equity_usd > self.seed_usd:
            raise ValueError("capital.seed_usd is below min_operating_equity_usd: the agent could never trade")
        return self


class AccountCfg(Strict):
    ibkr_account_id: str = ""
    dedicated: bool = False
    currency: str = "USD"


class BrokerCfg(Strict):
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    client_id: int = Field(ge=0)
    market_data_type: Literal[1, 2, 3, 4] = 3
    fractional_shares: bool = True
    connect_timeout_s: int = Field(ge=5, le=120, default=20)


# ----------------------------------------------------------------------------- universe


class Instrument(Strict):
    symbol: str = Field(min_length=1, max_length=12)
    sleeves: List[Sleeve] = Field(min_length=1)
    kind: Literal["etf", "stock"] = "stock"
    exchange: Optional[str] = None
    currency: Optional[str] = None
    sec_type: Literal["STK"] = "STK"


class UniverseProfile(Strict):
    default_exchange: str = "SMART"
    default_currency: str = "USD"
    core_holdings: Dict[str, float]
    instruments: List[Instrument] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "UniverseProfile":
        syms = [i.symbol for i in self.instruments]
        dups = sorted({s for s in syms if syms.count(s) > 1})
        if dups:
            raise ValueError(f"duplicate instruments: {dups}")
        if not self.core_holdings:
            raise ValueError("core_holdings must not be empty")
        if abs(sum(self.core_holdings.values()) - 1.0) > 1e-6:
            raise ValueError("core_holdings weights must sum to 1.0")
        by = {i.symbol: i for i in self.instruments}
        for s, w in self.core_holdings.items():
            if w <= 0:
                raise ValueError(f"core holding {s} has non-positive weight")
            if s not in by or "core" not in by[s].sleeves:
                raise ValueError(f"core holding {s} must be listed in instruments with sleeve 'core'")
        return self

    def instrument(self, symbol: str) -> Optional[Instrument]:
        """Instrument with exchange/currency defaults resolved, or None if not whitelisted."""
        for i in self.instruments:
            if i.symbol == symbol:
                return i.model_copy(update={
                    "exchange": i.exchange or self.default_exchange,
                    "currency": i.currency or self.default_currency,
                })
        return None

    def symbols(self, sleeve: Sleeve) -> List[str]:
        return [i.symbol for i in self.instruments if sleeve in i.sleeves]


class UniverseCfg(Strict):
    profile: str
    never: List[str] = Field(default_factory=list)
    profiles: Dict[str, UniverseProfile]

    @model_validator(mode="after")
    def _check(self) -> "UniverseCfg":
        if self.profile not in self.profiles:
            raise ValueError(f"universe.profile '{self.profile}' not in profiles {sorted(self.profiles)}")
        banned = sorted(set(self.never) & {i.symbol for i in self.active.instruments})
        if banned:
            raise ValueError(f"never-list symbols present in active profile: {banned}")
        return self

    @property
    def active(self) -> UniverseProfile:
        return self.profiles[self.profile]

    def is_allowed(self, symbol: str, sleeve: Sleeve) -> bool:
        inst = self.active.instrument(symbol)
        return inst is not None and sleeve in inst.sleeves and symbol not in self.never


# ----------------------------------------------------------------------------- sleeves / risk


class SleeveCfg(Strict):
    weight: float = Field(ge=0, le=1)
    band: float = Field(ge=0, le=0.5, default=0.05)
    max_positions: int = Field(ge=0, default=0)


class SleevesCfg(Strict):
    core: SleeveCfg
    trend: SleeveCfg
    spec: SleeveCfg
    cash: SleeveCfg
    rebalance: Literal["weekly", "monthly"] = "monthly"
    spec_profit_sweep_to_core: float = Field(ge=0, le=1, default=0.5)

    @model_validator(mode="after")
    def _check(self) -> "SleevesCfg":
        total = self.core.weight + self.trend.weight + self.spec.weight + self.cash.weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"sleeve weights sum to {total:.4f}; must be 1.0")
        for name in ACTIVE_SLEEVES:
            if self.get(name).max_positions < 1:
                raise ValueError(f"sleeves.{name}.max_positions must be >= 1")
        return self

    def get(self, sleeve: Sleeve) -> SleeveCfg:
        return getattr(self, sleeve)


class StopsCfg(Strict):
    method: Literal["atr", "pct"] = "atr"
    atr_period: int = Field(ge=5, le=50, default=14)
    atr_multiple: Dict[ActiveSleeve, float]
    pct_distance: Dict[ActiveSleeve, float]
    min_distance_pct: float = Field(gt=0, lt=0.5)
    max_distance_pct: Dict[ActiveSleeve, float]
    server_side: bool = True
    stop_type: Literal["STP", "STP LMT"] = "STP"
    stop_limit_offset_pct: float = Field(ge=0, le=0.05, default=0.01)
    never_widen: Literal[True] = True

    @model_validator(mode="after")
    def _check(self) -> "StopsCfg":
        for name, d in (("atr_multiple", self.atr_multiple), ("pct_distance", self.pct_distance),
                        ("max_distance_pct", self.max_distance_pct)):
            _require_keys(d, ACTIVE_SLEEVES, f"risk.stops.{name}")
            if any(v <= 0 for v in d.values()):
                raise ValueError(f"risk.stops.{name} values must be > 0")
        for s in ACTIVE_SLEEVES:
            if self.max_distance_pct[s] <= self.min_distance_pct:
                raise ValueError(f"risk.stops.max_distance_pct.{s} must exceed min_distance_pct")
            if self.pct_distance[s] > self.max_distance_pct[s]:
                raise ValueError(f"risk.stops.pct_distance.{s} exceeds max_distance_pct")
        return self


class TrendTargets(Strict):
    partial_take_r: float = Field(gt=0)
    partial_fraction: float = Field(gt=0, le=1)
    trail_atr_multiple: float = Field(gt=0)


class SpecTargets(Strict):
    take_profit_pct: float = Field(gt=0, le=2)
    time_stop_trading_days: int = Field(ge=1, le=120)


class TargetsCfg(Strict):
    trend: TrendTargets
    spec: SpecTargets


class RiskCfg(Strict):
    per_trade_risk_pct: Dict[ActiveSleeve, float]
    per_trade_risk_hard_cap_pct: Dict[ActiveSleeve, float]
    max_total_open_risk_pct: float = Field(gt=0, le=0.2)
    max_position_weight_pct: Dict[Sleeve, float]
    max_new_positions_per_week: int = Field(ge=0)
    max_turnover_pct_per_week: float = Field(gt=0, le=3)
    cooldown_days_after_stop_out: int = Field(ge=0)
    cooldown_days_after_exit: int = Field(ge=0, default=5)   # ANY full exit locks re-entry (sessions)
    no_averaging_down: Literal[True] = True
    max_extension_atr: float = Field(gt=0, le=5, default=1.5)  # no chasing: entry price may sit
    # at most this many ATRs above the 20d MA (enforced in code when bars are available)
    stops: StopsCfg
    targets: TargetsCfg

    @model_validator(mode="after")
    def _check(self) -> "RiskCfg":
        _require_keys(self.per_trade_risk_pct, ACTIVE_SLEEVES, "risk.per_trade_risk_pct")
        _require_keys(self.per_trade_risk_hard_cap_pct, ACTIVE_SLEEVES, "risk.per_trade_risk_hard_cap_pct")
        _require_keys(self.max_position_weight_pct, ALL_SLEEVES, "risk.max_position_weight_pct")
        for s in ACTIVE_SLEEVES:
            r, cap = self.per_trade_risk_pct[s], self.per_trade_risk_hard_cap_pct[s]
            if not (0 < r <= 0.05):
                raise ValueError(f"risk.per_trade_risk_pct.{s} must be in (0, 0.05]")
            if not (r <= cap <= 0.05):
                raise ValueError(f"risk.per_trade_risk_hard_cap_pct.{s} must be >= per_trade_risk_pct and <= 0.05")
        if any(not (0 < w <= 1) for w in self.max_position_weight_pct.values()):
            raise ValueError("risk.max_position_weight_pct values must be in (0, 1]")
        return self


class CircuitBreakersCfg(Strict):
    sleeve_drawdown_pause_pct: float = Field(gt=0, lt=1)
    total_drawdown_halt_pct: float = Field(gt=0, lt=1)
    daily_loss_pause_pct: float = Field(gt=0, lt=1)
    weekly_drawdown_pause_pct: float = Field(gt=0, lt=1, default=0.07)   # from week-open equity
    monthly_drawdown_pause_pct: float = Field(gt=0, lt=1, default=0.10)  # from month-open equity
    half_risk_drawdown_pct: float = Field(gt=0, lt=1, default=0.10)      # HWM dd -> half risk budget
    consecutive_losers_pause: int = Field(ge=2)                          # spec sleeve pause
    account_losing_streak_cooldown: int = Field(ge=2, default=3)         # any-active-sleeve streak
    account_losing_streak_days: int = Field(ge=1, default=2)             # entry pause length (sessions)
    symbol_stopout_lock_count: int = Field(ge=2, default=2)              # N stop-outs ...
    symbol_stopout_window_sessions: int = Field(ge=5, default=60)        # ... within this window ...
    symbol_stopout_lock_sessions: int = Field(ge=1, default=30)          # ... locks the symbol
    underperformer_lookback_trades: int = Field(ge=2, default=4)
    underperformer_threshold_r: float = Field(lt=0, default=-1.0)        # cum R below this ...
    underperformer_lock_sessions: int = Field(ge=1, default=60)          # ... benches the symbol
    data_stale_seconds: int = Field(ge=60)
    reconcile_mismatch: Literal["freeze"] = "freeze"

    @model_validator(mode="after")
    def _check(self) -> "CircuitBreakersCfg":
        if self.half_risk_drawdown_pct >= self.total_drawdown_halt_pct:
            raise ValueError("half_risk_drawdown_pct must sit below total_drawdown_halt_pct")
        return self


class ExecutionCfg(Strict):
    order_type: Literal["marketable_limit"] = "marketable_limit"
    limit_offset_bps: int = Field(ge=0, le=100)
    time_in_force: Literal["DAY"] = "DAY"
    rth_only: Literal[True] = True
    no_trade_first_minutes: int = Field(ge=0, le=120)
    no_trade_last_minutes: int = Field(ge=0, le=120)
    slippage_alert_bps: int = Field(ge=1)
    settled_cash_only: Literal[True] = True
    settlement_days: int = Field(ge=0, le=3, default=1)


# ----------------------------------------------------------------------------- cadence / llm / ops


class ClockTime(Strict):
    time: str

    @model_validator(mode="after")
    def _check(self) -> "ClockTime":
        if not _HHMM.match(self.time):
            raise ValueError(f"time '{self.time}' must be HH:MM (24h)")
        return self


class WeeklyClock(ClockTime):
    day: Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


class EventCfg(Strict):
    max_per_day: int = Field(ge=0, le=10)
    cooldown_minutes: int = Field(ge=0)
    min_materiality: float = Field(ge=0, le=1)
    min_abs_move_pct: float = Field(ge=0, le=1)


class CadenceCfg(Strict):
    market_timezone: str = "America/New_York"
    weekly_review: WeeklyClock
    daily_check: ClockTime
    daily_report: ClockTime
    event: EventCfg
    fast_loop_seconds: int = Field(ge=15, le=600)
    slow_loop_seconds: int = Field(ge=60, le=3600)
    news_poll_seconds: int = Field(ge=60, le=7200)


class SandboxCfg(Strict):
    runs_root: str = ""
    deny_read_globs: List[str] = Field(default_factory=list)
    webfetch_domains: List[str] = Field(default_factory=list)
    scrub_env: bool = True


class LLMCfg(Strict):
    runner: Literal["claude_code", "api"] = "claude_code"
    claude_bin: str = "claude"
    model: str = ""
    max_turns: Dict[RunType, int]
    timeout_seconds: Dict[RunType, int]
    retries_on_invalid: int = Field(ge=0, le=3)
    backoff_minutes_on_unavailable: List[int] = Field(min_length=1)
    daily_invocation_cap: int = Field(ge=1, le=50)   # upper bound = runaway-bug backstop ceiling
    tools: List[str] = Field(min_length=1)
    permission_mode: Literal["dontAsk"] = "dontAsk"
    sandbox: SandboxCfg = SandboxCfg()

    @model_validator(mode="after")
    def _check(self) -> "LLMCfg":
        _require_keys(self.max_turns, ("weekly", "daily", "event"), "llm.max_turns")
        _require_keys(self.timeout_seconds, ("weekly", "daily", "event"), "llm.timeout_seconds")
        bad = sorted(set(self.tools) - READ_ONLY_TOOLS)
        if bad:
            raise ValueError(f"llm.tools contains non read-only tools {bad}; allowed: {sorted(READ_ONLY_TOOLS)}")
        if any(v < 1 for v in self.max_turns.values()) or any(v < 60 for v in self.timeout_seconds.values()):
            raise ValueError("llm.max_turns must be >= 1 and llm.timeout_seconds >= 60")
        return self


class AlertsCfg(Strict):
    channels: List[Literal["stdout", "telegram", "email", "windows_toast"]] = Field(min_length=1)
    heartbeat_stale_minutes: int = Field(ge=2, le=120)
    dedupe_minutes: int = Field(ge=0, le=1440, default=30)


class KillSwitchCfg(Strict):
    file: str
    on_kill: Literal["cancel_open_orders", "liquidate_to_cash"] = "cancel_open_orders"


class JournalCfg(Strict):
    dir: str
    keep_raw_llm_output: bool = True


class GoLiveGateCfg(Strict):
    min_paper_calendar_days: int = Field(ge=1)
    min_weekly_runs: int = Field(ge=1)
    max_reconcile_freezes_30d: int = Field(ge=0)
    max_llm_fallback_rate: float = Field(ge=0, le=1)
    ack_env_var: str = "IBAGENT_LIVE_ACK"
    ack_value: str = "I_UNDERSTAND_REAL_MONEY"


# ----------------------------------------------------------------------------- root


class Mandate(Strict):
    version: Literal[1]
    mode: Literal["paper", "live"]
    base_currency: str = "USD"
    capital: CapitalCfg
    account: AccountCfg
    broker: BrokerCfg
    universe: UniverseCfg
    sleeves: SleevesCfg
    risk: RiskCfg
    circuit_breakers: CircuitBreakersCfg
    execution: ExecutionCfg
    cadence: CadenceCfg
    llm: LLMCfg
    alerts: AlertsCfg
    kill_switch: KillSwitchCfg
    journal: JournalCfg
    go_live_gate: GoLiveGateCfg

    @model_validator(mode="after")
    def _cross_checks(self) -> "Mandate":
        if self.mode == "live":
            if not self.account.ibkr_account_id:
                raise ValueError("live mode requires account.ibkr_account_id")
            if self.broker.port in PAPER_PORTS:
                raise ValueError(f"mode=live but broker.port {self.broker.port} is a paper port")
        elif self.broker.port in LIVE_PORTS:
            raise ValueError(f"mode=paper but broker.port {self.broker.port} is a LIVE port")
        for s in ACTIVE_SLEEVES:
            # At the configured seed every active sleeve must fund at least one min_position_usd position.
            if self.max_positions(s, self.capital.seed_usd) < 1:
                raise ValueError(
                    f"at seed_usd={self.capital.seed_usd:.0f} the {s} sleeve "
                    f"({self.sleeves.get(s).weight:.0%}) cannot fund one min_position_usd position; "
                    "raise seed_usd or lower capital.min_position_usd")
            # At scale, max_positions x per-position cap must be able to fill the sleeve.
            if self.risk.max_position_weight_pct[s] * self.sleeves.get(s).max_positions < self.sleeves.get(s).weight:
                raise ValueError(f"{s}: max_positions x max_position_weight_pct cannot fill the sleeve weight")
        return self

    # ---- capital-scaled sizing (fractions of *current* pot equity) ----
    def sleeve_equity(self, pot_equity: float, sleeve: Sleeve) -> float:
        return max(0.0, pot_equity) * self.sleeves.get(sleeve).weight

    def max_positions(self, sleeve: ActiveSleeve, pot_equity: float) -> int:
        by_capital = math.floor(self.sleeve_equity(pot_equity, sleeve) / self.capital.min_position_usd)
        return max(0, min(self.sleeves.get(sleeve).max_positions, by_capital))

    def per_trade_risk_usd(self, sleeve: ActiveSleeve, pot_equity: float, hard_cap: bool = False) -> float:
        table = self.risk.per_trade_risk_hard_cap_pct if hard_cap else self.risk.per_trade_risk_pct
        return max(0.0, pot_equity) * table[sleeve]

    def position_cap_usd(self, sleeve: Sleeve, pot_equity: float) -> float:
        """Per-position notional cap. The % cap rules at scale; the USD floor rules for small pots,
        but a position can never exceed its sleeve's equity."""
        eq = max(0.0, pot_equity)
        pct_cap = eq * self.risk.max_position_weight_pct[sleeve]
        return min(self.sleeve_equity(eq, sleeve), max(pct_cap, self.capital.min_position_usd))

    def is_operating(self, pot_equity: float) -> bool:
        return pot_equity >= self.capital.min_operating_equity_usd

    def active_weight_cap(self) -> float:
        """Maximum combined trend+spec weight the model may request (before risk_multiplier)."""
        return self.sleeves.trend.weight + self.sleeves.spec.weight


# ----------------------------------------------------------------------------- loading


def _apply_overrides(data: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply dotted-key overrides, e.g. {"capital.seed_usd": 2500}. Creates no new keys."""
    for dotted, value in overrides.items():
        node = data
        parts = dotted.split(".")
        for p in parts[:-1]:
            if not isinstance(node, dict) or p not in node:
                raise MandateError(f"override '{dotted}': unknown path")
            node = node[p]
        if not isinstance(node, dict) or parts[-1] not in node:
            raise MandateError(f"override '{dotted}': unknown key")
        node[parts[-1]] = value
    return data


def mandate_from_dict(data: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> Mandate:
    try:
        return Mandate.model_validate(_apply_overrides(dict(data), overrides or {}))
    except MandateError:
        raise
    except Exception as exc:  # pydantic ValidationError and friends -> one error type for callers
        raise MandateError(str(exc)) from exc


def load_mandate(path: Path | str, overrides: Optional[Dict[str, Any]] = None) -> Mandate:
    p = Path(path)
    if not p.is_file():
        raise MandateError(f"mandate file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise MandateError("mandate must be a YAML mapping")
    return mandate_from_dict(data, overrides)


def parse_override(text: str) -> tuple[str, Any]:
    """'capital.seed_usd=2500' -> ('capital.seed_usd', 2500). Values parsed as YAML scalars."""
    if "=" not in text:
        raise MandateError(f"override must look like key.path=value, got '{text}'")
    key, raw = text.split("=", 1)
    return key.strip(), yaml.safe_load(raw)
