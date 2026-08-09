"""Central configuration, loaded from environment / .env.

Nothing here places trades. The one switch that matters is LIVE_TRADING;
it stays False unless explicitly set, so the default posture is always paper.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── Safety gate ──────────────────────────────────────────
    live_trading: bool = False

    # ── Public sharing ───────────────────────────────────────
    # When set, the dashboard is read-only for everyone EXCEPT requests that
    # present this key (header X-Owner-Key). Empty = no restriction (local dev).
    owner_key: str = ""

    # ── Polymarket US API creds (used when live_trading) ─────
    # Created at polymarket.us/developer after identity verification in the app.
    # The secret is shown once; it never leaves the backend.
    polymarket_key_id: str = ""
    polymarket_secret_key: str = ""

    # Hard ceiling on a single live order, in dollars. Enforced inside the
    # executor, so a sizing bug upstream still cannot spend more than this.
    live_max_usd_per_order: float = 5.0

    # Slippage tolerance sent with each market order, in basis points.
    live_slippage_bips: int = 200

    # When true, live orders go through the SDK's `preview` endpoint instead of
    # being submitted. Exercises the whole path without risking money — leave it
    # on for the first run.
    live_dry_run: bool = True

    # Post passively (maker) instead of crossing the spread (taker). Taker fees
    # are 6% x (1-p) of stake; makers get a 1.25% x (1-p) rebate, and you save
    # the half-spread. The cost is that a resting order only fills when someone
    # chooses to hit it, which skews toward the price moving against you.
    live_maker: bool = False

    # ── Wallet / CLOB creds (international book — unused by US) ──
    polygon_private_key: str = ""
    clob_api_key: str = ""
    clob_api_secret: str = ""
    clob_api_passphrase: str = ""

    # ── Endpoints ────────────────────────────────────────────
    clob_host: str = "https://clob.polymarket.com"
    data_api: str = "https://data-api.polymarket.com"
    chain_id: int = 137

    # ── Risk defaults ────────────────────────────────────────
    bankroll_usd: float = 1000.0
    max_usd_per_position: float = 5.0
    max_open_positions: int = 20
    daily_loss_kill_pct: float = 0.10
    price_band_low: float = 0.05
    price_band_high: float = 0.95

    # ── Engine ───────────────────────────────────────────────
    db_path: str = "copybot.sqlite"
    engine_interval_seconds: int = 30

    # ── Server ───────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
