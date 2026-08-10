"""Live config. Merges .env defaults with dashboard overrides in the DB.

Covers risk limits AND Autopilot. The engine reads a fresh view each tick, so
edits saved from Settings take effect on the next tick with no restart.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from app.config import Settings
from app.db.repo import Database

# field -> python type (used to (de)serialize the string values in the DB)
_RISK_FIELDS: dict[str, type] = {
    "bankroll_usd": float,
    "size_mode": str,               # 'fixed' (flat $) | 'equity_pct' (% of equity)
    "size_pct": float,              # used when size_mode == 'equity_pct'
    "max_usd_per_position": float,  # used when size_mode == 'fixed'
    "max_open_positions": int,
    "daily_loss_kill_pct": float,
    "price_band_low": float,
    "price_band_high": float,
    "engine_paused": bool,
    # Copy the trader OUT as well as in. Off = hold every copy to resolution.
    # Exits cost a second spread crossing plus taker fees, which on short holds
    # exceeds what the trader's timing is worth.
    "follow_exits": bool,
    # Refuse to chase: skip when our price is more than this fraction above what
    # the copied trader paid. 0 disables it. Measured across 135 of their
    # positions, we pay more than they did on 76% of trades, median +7c on a
    # ~50c contract — the largest single drag on the strategy.
    "max_entry_gap_pct": float,
}
_AUTO_FIELDS: dict[str, type] = {
    "autopilot_enabled": bool,
    "autopilot_rank": str,       # 'roi' | 'pnl' | 'pnl_30d'
    "autopilot_count": int,
    "autopilot_min_volume": float,
}
_FIELDS = {**_RISK_FIELDS, **_AUTO_FIELDS}
_AUTOPILOT_RANKS = {"roi", "pnl", "pnl_30d", "churn"}


@dataclass
class RiskView:
    bankroll_usd: float
    size_mode: str
    size_pct: float
    max_usd_per_position: float
    max_open_positions: int
    daily_loss_kill_pct: float
    price_band_low: float
    price_band_high: float
    engine_paused: bool
    follow_exits: bool
    max_entry_gap_pct: float


@dataclass
class AutopilotView:
    autopilot_enabled: bool
    autopilot_rank: str
    autopilot_count: int
    autopilot_min_volume: float


def _coerce(key: str, value: object) -> object:
    t = _FIELDS[key]
    if t is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if t is str:
        return str(value)
    return t(value)


def _validate(view: dict) -> None:
    if view["bankroll_usd"] <= 0:
        raise ValueError("bankroll_usd must be > 0")
    if view["max_usd_per_position"] <= 0:
        raise ValueError("max_usd_per_position must be > 0")
    if view["size_mode"] not in ("fixed", "equity_pct"):
        raise ValueError("size_mode must be 'fixed' or 'equity_pct'")
    if not (0 < view["size_pct"] <= 0.5):
        raise ValueError("size_pct must be between 0 and 0.5")
    if view["max_open_positions"] < 1:
        raise ValueError("max_open_positions must be >= 1")
    if not (0 <= view["max_entry_gap_pct"] <= 5):
        raise ValueError("max_entry_gap_pct must be between 0 and 5")
    if not (0 <= view["daily_loss_kill_pct"] <= 1):
        raise ValueError("daily_loss_kill_pct must be between 0 and 1")
    lo, hi = view["price_band_low"], view["price_band_high"]
    if not (0 <= lo < hi <= 1):
        raise ValueError("price band must satisfy 0 <= low < high <= 1")
    if view["autopilot_rank"] not in _AUTOPILOT_RANKS:
        raise ValueError(f"autopilot_rank must be one of {sorted(_AUTOPILOT_RANKS)}")
    if not (1 <= view["autopilot_count"] <= 25):
        raise ValueError("autopilot_count must be between 1 and 25")
    if view["autopilot_min_volume"] < 0:
        raise ValueError("autopilot_min_volume must be >= 0")


class ConfigStore:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self._defaults: dict[str, object] = {
            "bankroll_usd": settings.bankroll_usd,
            "size_mode": "fixed",
            "size_pct": 0.02,
            "max_usd_per_position": settings.max_usd_per_position,
            "max_open_positions": settings.max_open_positions,
            "daily_loss_kill_pct": settings.daily_loss_kill_pct,
            "price_band_low": settings.price_band_low,
            "price_band_high": settings.price_band_high,
            "engine_paused": False,
            # Default on, so paper behaviour is unchanged. Paper exits are free;
            # only a live venue charges for them.
            "follow_exits": True,
            # Off by default: it has a known trap. A price at or below theirs
            # usually means the position has moved AGAINST them, so filtering
            # for a good entry can select their losers. The counterfactual book
            # is what settles whether it helps.
            "max_entry_gap_pct": 0.0,
            "autopilot_enabled": False,
            "autopilot_rank": "roi",
            "autopilot_count": 5,
            "autopilot_min_volume": 100_000.0,
        }

    def effective(self) -> dict:
        eff = dict(self._defaults)
        for row in self.db.get_all_config():
            if row["key"] in _FIELDS:
                eff[row["key"]] = _coerce(row["key"], row["value"])
        return eff

    def risk(self) -> RiskView:
        eff = self.effective()
        return RiskView(**{k: eff[k] for k in _RISK_FIELDS})  # type: ignore[arg-type]

    def autopilot(self) -> AutopilotView:
        eff = self.effective()
        return AutopilotView(**{k: eff[k] for k in _AUTO_FIELDS})  # type: ignore[arg-type]

    def update(self, patch: dict) -> dict:
        """Validate the resulting config, then persist changed fields."""
        merged = self.effective()
        for key, value in patch.items():
            if key not in _FIELDS:
                raise ValueError(f"unknown setting '{key}'")
            merged[key] = _coerce(key, value)
        _validate(merged)
        for key in patch:
            if key in _FIELDS:
                self.db.set_config(key, str(merged[key]))
        return merged

    def as_dict(self) -> dict:
        return {"risk": asdict(self.risk()), "autopilot": asdict(self.autopilot())}
