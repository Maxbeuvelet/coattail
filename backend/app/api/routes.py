"""HTTP API for the dashboard.

Read-only market data (leaderboard/positions/snapshot) + the copy-trade surface
(follows, book, activity, engine). Live order placement stays behind the
LIVE_TRADING gate and lands in Phase 4.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.polymarket.us_pricing import US_FEE_PER_SHARE

router = APIRouter(prefix="/api")


def require_owner(
    request: Request,
    x_owner_key: str | None = Header(default=None, alias="X-Owner-Key"),
) -> None:
    """Gate for mutating endpoints. If an OWNER_KEY is configured, the caller
    must present it; otherwise (local dev) everything is allowed."""
    key = request.app.state.settings.owner_key
    if key and x_owner_key != key:
        raise HTTPException(403, "read-only view — owner key required to make changes")


@router.get("/whoami")
async def whoami(
    request: Request,
    x_owner_key: str | None = Header(default=None, alias="X-Owner-Key"),
) -> dict:
    """Lets the dashboard know whether this visitor can control the bot."""
    key = request.app.state.settings.owner_key
    return {"authRequired": bool(key), "owner": (not key) or (x_owner_key == key)}


# ─────────────────────────────────────────────────────────────
#  Status + market data (read-only)
# ─────────────────────────────────────────────────────────────
def _risk_out(r) -> dict:
    return {
        "bankrollUsd": r.bankroll_usd,
        "sizeMode": r.size_mode,
        "sizePct": r.size_pct,
        "maxUsdPerPosition": r.max_usd_per_position,
        "maxOpenPositions": r.max_open_positions,
        "dailyLossKillPct": r.daily_loss_kill_pct,
        "priceBand": [r.price_band_low, r.price_band_high],
        "enginePaused": r.engine_paused,
    }


def _autopilot_out(a) -> dict:
    return {
        "enabled": a.autopilot_enabled,
        "rank": a.autopilot_rank,
        "count": a.autopilot_count,
        "minVolume": a.autopilot_min_volume,
    }


def _settings_out(store) -> dict:
    return {**_risk_out(store.risk()), "autopilot": _autopilot_out(store.autopilot())}


@router.get("/status")
async def status(request: Request) -> dict:
    s = request.app.state.settings
    sched = request.app.state.scheduler
    store = request.app.state.config_store
    r = store.risk()
    return {
        "liveTrading": s.live_trading,
        "mode": "LIVE" if s.live_trading else "PAPER",
        "walletConfigured": bool(s.polygon_private_key) if s.live_trading else False,
        "engine": {
            "intervalSeconds": s.engine_interval_seconds,
            "lastTick": sched.last_summary,
            "paused": r.engine_paused,
        },
        "risk": _risk_out(r),
        "autopilot": _autopilot_out(store.autopilot()),
    }


class SettingsPatch(BaseModel):
    bankrollUsd: float | None = Field(default=None, gt=0)
    sizeMode: str | None = Field(default=None, pattern="^(fixed|equity_pct)$")
    sizePct: float | None = Field(default=None, gt=0, le=0.5)
    maxUsdPerPosition: float | None = Field(default=None, gt=0)
    maxOpenPositions: int | None = Field(default=None, ge=1)
    dailyLossKillPct: float | None = Field(default=None, ge=0, le=1)
    priceBandLow: float | None = Field(default=None, ge=0, le=1)
    priceBandHigh: float | None = Field(default=None, ge=0, le=1)
    enginePaused: bool | None = None
    autopilotEnabled: bool | None = None
    autopilotRank: str | None = Field(default=None, pattern="^(roi|pnl|pnl_30d|churn)$")
    autopilotCount: int | None = Field(default=None, ge=1, le=25)
    autopilotMinVolume: float | None = Field(default=None, ge=0)


_PATCH_TO_FIELD = {
    "bankrollUsd": "bankroll_usd",
    "sizeMode": "size_mode",
    "sizePct": "size_pct",
    "maxUsdPerPosition": "max_usd_per_position",
    "maxOpenPositions": "max_open_positions",
    "dailyLossKillPct": "daily_loss_kill_pct",
    "priceBandLow": "price_band_low",
    "priceBandHigh": "price_band_high",
    "enginePaused": "engine_paused",
    "autopilotEnabled": "autopilot_enabled",
    "autopilotRank": "autopilot_rank",
    "autopilotCount": "autopilot_count",
    "autopilotMinVolume": "autopilot_min_volume",
}


@router.get("/settings")
async def get_settings(request: Request) -> dict:
    return _settings_out(request.app.state.config_store)


@router.patch("/settings", dependencies=[Depends(require_owner)])
async def patch_settings(request: Request, body: SettingsPatch) -> dict:
    patch = {
        _PATCH_TO_FIELD[k]: v
        for k, v in body.model_dump(exclude_none=True).items()
        if k in _PATCH_TO_FIELD
    }
    if not patch:
        raise HTTPException(400, "no settings to update")
    try:
        request.app.state.config_store.update(patch)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    request.app.state.db.log("engine", f"Settings updated: {', '.join(patch)}")
    return _settings_out(request.app.state.config_store)


@router.post("/engine/reset", dependencies=[Depends(require_owner)])
async def engine_reset(request: Request) -> dict:
    """Wipe follows, book and history (keeps your risk/autopilot config)."""
    request.app.state.db.reset_book()
    # Force Autopilot to re-select on the next tick instead of waiting out its
    # throttle — otherwise the book sits empty for minutes after a reset.
    request.app.state.engine._autopilot_last_run = None
    request.app.state.db.log("engine", "Book reset — follows, positions and history cleared")
    return {"ok": True}


@router.get("/leaderboard")
async def leaderboard(
    request: Request,
    window: str = Query("ALL", pattern="^(ALL|MONTH)$"),
    top: int = Query(10, ge=1, le=50),
    orderBy: str = Query("PNL", pattern="^(PNL|VOLUME)$"),
) -> list[dict]:
    return await request.app.state.data_client.leaderboard(window, top, orderBy)


@router.get("/positions/{wallet}")
async def positions(request: Request, wallet: str, limit: int = Query(6, ge=1, le=50)) -> list[dict]:
    return await request.app.state.data_client.open_positions(wallet, limit)


@router.get("/snapshot")
async def snapshot(request: Request, top: int = Query(10, ge=1, le=50)) -> dict:
    client = request.app.state.data_client
    try:
        return await client.snapshot(top)
    except Exception as exc:  # noqa: BLE001
        from app.sample_data import load_sample

        sample = load_sample()
        if sample is not None:
            sample["_note"] = f"live data-api unreachable ({type(exc).__name__}); showing bundled sample"
            return sample
        raise


# ─────────────────────────────────────────────────────────────
#  Follows
# ─────────────────────────────────────────────────────────────
class FollowIn(BaseModel):
    wallet: str = Field(min_length=4)
    name: str = Field(min_length=1)
    allocationUsd: float | None = Field(default=None, ge=0)


class AllocationIn(BaseModel):
    allocationUsd: float | None = Field(default=None, ge=0)


def _follow_out(row: dict) -> dict:
    return {
        "wallet": row["wallet"],
        "name": row["name"],
        "allocationUsd": row["allocation_usd"],
        "active": bool(row["active"]),
        "auto": bool(row.get("auto", 0)),
        "createdAt": row["created_at"],
    }


@router.get("/follows")
async def list_follows(request: Request) -> list[dict]:
    return [_follow_out(r) for r in request.app.state.db.list_follows()]


@router.post("/follows", status_code=201, dependencies=[Depends(require_owner)])
async def add_follow(request: Request, body: FollowIn) -> dict:
    row = request.app.state.db.add_follow(body.wallet.lower(), body.name, body.allocationUsd)
    request.app.state.db.log("engine", f"Now following {body.name}", wallet=body.wallet.lower(), name=body.name)
    return _follow_out(row)


@router.delete("/follows/{wallet}", dependencies=[Depends(require_owner)])
async def remove_follow(request: Request, wallet: str) -> dict:
    db = request.app.state.db
    existing = db.get_follow(wallet.lower())
    db.remove_follow(wallet.lower())
    if existing:
        db.log("engine", f"Unfollowed {existing['name']}", wallet=wallet.lower(), name=existing["name"])
    return {"ok": True}


@router.patch("/follows/{wallet}", dependencies=[Depends(require_owner)])
async def set_allocation(request: Request, wallet: str, body: AllocationIn) -> dict:
    db = request.app.state.db
    if not db.get_follow(wallet.lower()):
        raise HTTPException(404, "not following that wallet")
    db.set_allocation(wallet.lower(), body.allocationUsd)
    return _follow_out(db.get_follow(wallet.lower()))


# ─────────────────────────────────────────────────────────────
#  Book + activity
# ─────────────────────────────────────────────────────────────
def _position_out(p: dict) -> dict:
    cur_value = round(p["shares"] * p["cur_price"], 2)
    unrealized = round(cur_value - p["stake_usd"], 2)
    return {
        "id": p["id"],
        "wallet": p["wallet"],
        "name": p["name"],
        "title": p["title"],
        "outcome": p["outcome"],
        "entryPrice": p["entry_price"],
        "curPrice": p["cur_price"],
        "shares": p["shares"],
        "stakeUsd": p["stake_usd"],
        "curValue": cur_value,
        "unrealized": unrealized,
        "status": p["status"],
        "openedAt": p["opened_at"],
        "exitPrice": p.get("exit_price"),
        "closedAt": p.get("closed_at"),
        "realizedPnl": p.get("realized_pnl"),
        # US shadow: the same trade priced on Polymarket US (null if unmatched),
        # exposed so the comparison is auditable trade-by-trade.
        "usEntry": p.get("us_entry"),
        "usExit": p.get("us_exit"),
        "usRealized": p.get("us_realized"),
    }


@router.get("/book")
async def book(request: Request) -> dict:
    db = request.app.state.db
    engine = request.app.state.engine
    return {
        "account": engine.account(),
        "open": [_position_out(p) for p in db.open_positions()],
        "closed": [_position_out(p) for p in db.closed_positions(100)],
    }


def _us_row(p: dict) -> dict:
    """One line of the US book: the bet, the stake, and the gain/loss — priced
    on Polymarket US. Closed rows use realized P&L; open rows mark to the last
    US price (same fee applied) so the number is comparable."""
    stake = p["stake_usd"]
    entry = p["us_entry"] or 0.0
    shares = stake / entry if entry > 0 else 0.0
    if p["status"] == "closed":
        pnl = p.get("us_realized")
        price = p.get("us_exit")
        when = p.get("closed_at")
    else:
        mark = p.get("us_cur") or entry
        pnl = round(shares * mark - stake - shares * US_FEE_PER_SHARE, 2)
        price = mark
        when = p.get("opened_at")
    return {
        "id": p["id"],
        "title": p["title"],
        "outcome": p["outcome"],
        "stakeUsd": round(stake, 2),
        "usEntry": entry,
        "usPrice": price,          # exit price (closed) or last mark (open)
        "pnl": pnl,
        "status": p["status"],
        "at": when,
    }


@router.get("/us-book")
async def us_book(request: Request) -> dict:
    """Standalone Polymarket US book: the same copied bets, priced on US. Simple
    by design — what the bet was, how much was placed, what it made or lost."""
    db = request.app.state.db
    rows = [_us_row(p) for p in db.us_positions()]
    open_rows = [r for r in rows if r["status"] == "open"]
    closed_rows = [r for r in rows if r["status"] == "closed"]
    realized = round(sum(r["pnl"] or 0 for r in closed_rows), 2)
    unrealized = round(sum(r["pnl"] or 0 for r in open_rows), 2)
    bankroll = request.app.state.engine.account()["bankroll"]
    return {
        "open": open_rows,
        "closed": closed_rows,
        "realized": realized,
        "unrealized": unrealized,
        "openCount": len(open_rows),
        "closedCount": len(closed_rows),
        "equity": round(bankroll + realized + unrealized, 2),
        "bankroll": bankroll,
    }


@router.get("/performance")
async def performance(request: Request) -> dict:
    """Realized-trade stats + a cumulative equity curve. The single 'is it
    working?' view."""
    db = request.app.state.db
    account = request.app.state.engine.account()
    p = db.performance()

    n = int(p.get("n", 0) or 0)
    wins = int(p.get("wins", 0) or 0)
    losses = int(p.get("losses", 0) or 0)
    decided = wins + losses
    total = float(p.get("total", 0) or 0)
    gross_win = float(p.get("gross_win", 0) or 0)
    gross_loss = abs(float(p.get("gross_loss", 0) or 0))

    # Cumulative realized equity over time, seeded at the bankroll.
    bankroll = account["bankroll"]
    cum = 0.0
    curve = [{"t": None, "equity": bankroll, "realized": 0.0}]
    for row in db.realized_series():
        cum += float(row["realized_pnl"] or 0)
        curve.append({
            "t": row["closed_at"],
            "equity": round(bankroll + cum, 2),
            "realized": round(cum, 2),
        })

    # ── US shadow book: the same trades, priced on Polymarket US ──
    us = db.us_performance()
    us_cum = 0.0
    us_curve = [{"t": None, "equity": bankroll, "realized": 0.0}]
    for row in db.us_realized_series():
        us_cum += float(row["us_realized"] or 0)
        us_curve.append({
            "t": row["closed_at"],
            "equity": round(bankroll + us_cum, 2),
            "realized": round(us_cum, 2),
        })
    us_n = int(us.get("n", 0) or 0)
    us_wins = int(us.get("wins", 0) or 0)
    us_losses = int(us.get("losses", 0) or 0)
    us_decided = us_wins + us_losses
    us_total_trades = int(us.get("totalTrades", 0) or 0)
    us_matched = int(us.get("matched", 0) or 0)
    us_own_matched = round(float(us.get("own_total", 0) or 0), 2)  # Coattail P&L on the same trades
    us_shadow = {
        "closedCount": us_n,
        "realizedTotal": round(float(us.get("total", 0) or 0), 2),
        "ownRealizedMatched": us_own_matched,
        "wins": us_wins,
        "losses": us_losses,
        "winRate": round(us_wins / us_decided, 4) if us_decided else None,
        "matched": us_matched,          # trades we could price on US
        "totalTrades": us_total_trades,  # all trades, matched or not
        "matchRate": round(us_matched / us_total_trades, 4) if us_total_trades else None,
        "equityCurve": us_curve,
    }

    return {
        "closedCount": n,
        "wins": wins,
        "losses": losses,
        "winRate": round(wins / decided, 4) if decided else None,
        "realizedTotal": round(total, 2),
        "avgPnl": round(total / n, 2) if n else 0.0,
        "bestPnl": round(float(p.get("best", 0) or 0), 2),
        "worstPnl": round(float(p.get("worst", 0) or 0), 2),
        "profitFactor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "account": account,
        "equityCurve": curve,
        "usShadow": us_shadow,
    }


@router.get("/activity")
async def activity(request: Request, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    rows = request.app.state.db.recent_activity(limit)
    return [
        {
            "id": r["id"],
            "ts": r["ts"],
            "kind": r["kind"],
            "wallet": r["wallet"],
            "name": r["name"],
            "title": r["title"],
            "outcome": r["outcome"],
            "detail": r["detail"],
            "amount": r["amount"],
        }
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────
#  Engine control
# ─────────────────────────────────────────────────────────────
@router.post("/engine/tick", dependencies=[Depends(require_owner)])
async def engine_tick(request: Request) -> dict:
    """Run one engine tick immediately (paper). Handy for testing without
    waiting for the interval."""
    return await request.app.state.scheduler.tick_now()
