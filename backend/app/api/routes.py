"""HTTP API for the dashboard.

Read-only market data (leaderboard/positions/snapshot) + the copy-trade surface
(follows, book, activity, engine). Live order placement stays behind the
LIVE_TRADING gate and lands in Phase 4.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.polymarket import us_account
from app.polymarket.us_pricing import US_FEE_RATE

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
        "followExits": r.follow_exits,
        "maxEntryGapPct": r.max_entry_gap_pct,
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
    # Report the executor that is actually installed, not what was requested.
    # LIVE_TRADING=true with bad credentials falls back to paper, and saying
    # "LIVE" there would be exactly the wrong answer to "am I armed?".
    ex = request.app.state.engine.executor
    mode = ex.mode                      # PAPER | LIVE | LIVE-DRYRUN
    placing_orders = mode == "LIVE"     # dry run previews, it does not trade
    return {
        "liveTrading": placing_orders,
        "mode": mode,
        # What the config asked for — differs from `mode` when arming failed.
        "configuredLive": s.live_trading,
        "dryRun": mode == "LIVE-DRYRUN",
        "maxUsdPerOrder": s.live_max_usd_per_order if mode.startswith("LIVE") else None,
        # Passive (maker) orders rest on the book instead of crossing it, so
        # some copies sit as unfilled orders rather than positions.
        "maker": bool(getattr(ex, "maker", False)),
        "pendingOrders": len(request.app.state.db.pending_positions()),
        "walletConfigured": bool(s.polymarket_key_id and s.polymarket_secret_key),
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
    followExits: bool | None = None
    maxEntryGapPct: float | None = Field(default=None, ge=0, le=5)
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
    "followExits": "follow_exits",
    "maxEntryGapPct": "max_entry_gap_pct",
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
        pnl = round(shares * mark - stake - stake * US_FEE_RATE, 2)
        price = mark
        when = p.get("opened_at")
    whale_entry = p.get("entry_price") or 0.0
    return {
        "id": p["id"],
        "title": p["title"],
        "outcome": p["outcome"],
        "stakeUsd": round(stake, 2),
        "whaleEntry": round(whale_entry, 4),   # what the whale/international paid
        "usEntry": round(entry, 4),            # what US would have cost
        "gap": round(entry - whale_entry, 4),  # +US pricier, −US cheaper
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


@router.get("/maker-shadow")
async def maker_shadow(request: Request) -> dict:
    """Would resting on the book beat crossing it?

    The median Polymarket US spread is 28% of mid. Crossing it on entry and exit
    costs more than the strategy's entire per-trade edge, so the only lever left
    is to rest passively and collect the spread instead of paying it. The catch
    is that a resting order only fills when someone chooses to hit it — this
    measures how often that actually happens.
    """
    m = request.app.state.db.maker_stats()
    n = int(m.get("n", 0) or 0)
    filled = int(m.get("filled", 0) or 0)
    f = lambda k: (round(float(m[k]), 4) if m.get(k) is not None else None)  # noqa: E731
    return {
        "tracked": n,
        "wouldHaveFilled": filled,
        "fillRate": round(filled / n, 4) if n else None,
        "avgSaving": f("avg_saving"),
        "avgSavingPct": f("avg_saving_pct"),
        "avgChecks": f("avg_checks"),
        "returnIfFilled": f("filled_return"),
        "returnAll": f("all_return"),
    }


@router.get("/match-split")
async def match_split(request: Request) -> dict:
    """Trades that exist on Polymarket US vs those that don't, compared on
    return per dollar staked. Answers whether the live bot's underperformance is
    execution or simply a worse subset of markets."""
    rows = []
    for r in request.app.state.db.match_split():
        rows.append({
            "group": r["grp"],
            "count": int(r["n"] or 0),
            "avgReturn": round(float(r["avg_return"]), 4) if r["avg_return"] is not None else None,
            "winRate": round(float(r["win_rate"]), 4) if r["win_rate"] is not None else None,
            "avgEntryPrice": round(float(r["avg_entry"]), 4) if r["avg_entry"] is not None else None,
            "avgWhaleGap": round(float(r["avg_gap"]), 4) if r["avg_gap"] is not None else None,
        })
    return {"groups": rows}


@router.get("/skipped")
async def skipped(request: Request) -> dict:
    """Did declining these trades actually help?

    A filter can only be judged against what it rejected. This compares the
    counterfactual return of declined trades against the realized return of
    taken ones — if the skipped set did BETTER, the filter is costing money.
    """
    db = request.app.state.db
    by_reason = []
    for row in db.skip_stats():
        by_reason.append({
            "reason": row["reason"],
            "count": int(row["n"] or 0),
            "resolved": int(row["resolved"] or 0),
            "avgReturn": round(float(row["avg_return"]), 4) if row["avg_return"] is not None else None,
            "winRate": round(float(row["win_rate"]), 4) if row["win_rate"] is not None else None,
            "avgEntryGap": round(float(row["avg_gap"]), 4) if row["avg_gap"] is not None else None,
        })

    # The comparison that matters: taken vs declined, on the same measure.
    taken = [
        (p["realized_pnl"] or 0) / p["stake_usd"]
        for p in db.closed_positions(500) if p["stake_usd"]
    ]
    resolved = [r for r in by_reason if r["resolved"]]
    skipped_ret = [
        r["avgReturn"] * r["resolved"] for r in resolved if r["avgReturn"] is not None
    ]
    skipped_n = sum(r["resolved"] for r in resolved if r["avgReturn"] is not None)
    return {
        "byReason": by_reason,
        "takenCount": len(taken),
        "takenAvgReturn": round(sum(taken) / len(taken), 4) if taken else None,
        "skippedResolved": skipped_n,
        "skippedAvgReturn": round(sum(skipped_ret) / skipped_n, 4) if skipped_n else None,
    }


@router.get("/live-book")
async def live_book(request: Request) -> dict:
    """Real money: what the Polymarket US account actually holds.

    Read from the venue, not from our SQLite book, because the two can disagree —
    and when they do, the exchange is right.
    """
    s = request.app.state.settings
    return await us_account.live_book(s.polymarket_key_id, s.polymarket_secret_key)


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

    # ── US shadow books: the same trades, priced on Polymarket US ──
    def shadow(perf: dict, series: list[dict], pnl_col: str) -> dict:
        cum = 0.0
        pts = [{"t": None, "equity": bankroll, "realized": 0.0}]
        for row in series:
            cum += float(row[pnl_col] or 0)
            pts.append({
                "t": row["closed_at"],
                "equity": round(bankroll + cum, 2),
                "realized": round(cum, 2),
            })
        wins_ = int(perf.get("wins", 0) or 0)
        losses_ = int(perf.get("losses", 0) or 0)
        decided_ = wins_ + losses_
        matched_ = int(perf.get("matched", 0) or 0)
        tried_ = int(perf.get("totalTrades", 0) or 0)
        return {
            "closedCount": int(perf.get("n", 0) or 0),
            "realizedTotal": round(float(perf.get("total", 0) or 0), 2),
            # Coattail P&L on the SAME trades (fair head-to-head)
            "ownRealizedMatched": round(float(perf.get("own_total", 0) or 0), 2),
            "wins": wins_,
            "losses": losses_,
            "winRate": round(wins_ / decided_, 4) if decided_ else None,
            "matched": matched_,   # trades we could price on US
            "totalTrades": tried_,  # all trades a lookup was attempted for
            "matchRate": round(matched_ / tried_, 4) if tried_ else None,
            "equityCurve": pts,
        }

    # How much worse our entry was than the trader's own.
    wg = db.whale_gap()
    wg_n = int(wg.get("n", 0) or 0)
    whale_gap = {
        "trades": wg_n,
        "avgGap": round(float(wg.get("avg_gap") or 0), 4),
        "avgPct": round(float(wg.get("avg_pct") or 0), 4),
        "worseCount": int(wg.get("worse", 0) or 0),
        "worseRate": round(int(wg.get("worse", 0) or 0) / wg_n, 4) if wg_n else None,
    } if wg_n else None

    us_shadow = shadow(db.us_performance(), db.us_realized_series(), "us_realized")
    us_shadow_v2 = shadow(db.us2_performance(), db.us2_realized_series(), "us2_realized")

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
        "usShadowV2": us_shadow_v2,
        "whaleGap": whale_gap,
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
