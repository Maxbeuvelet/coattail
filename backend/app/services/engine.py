"""The follow engine.

Each tick: for every active followed trader, pull their current open positions
and diff against our book —
  • they hold something we don't  → maybe open a copy (subject to risk filters)
  • we hold something they exited  → close our copy, realize P&L
  • we both hold it                → mark our copy to their current price

Runs the same in paper and (Phase 4) live mode; only the Executor differs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.repo import Database
from app.polymarket.data_client import DataClient
from app.services.config_store import AutopilotView, ConfigStore, RiskView
from app.services.executor import Executor

log = logging.getLogger("copybot.engine")


# The leaderboard churns slowly; re-selecting the auto-follow set every few
# minutes is plenty and keeps the per-trader position lookups off the hot path.
_AUTOPILOT_SYNC_SECONDS = 300

# "Fast" (churn) mode: only follow/copy positions that resolve within this many
# days, so the book turns over quickly and closed trades accrue fast.
_FAST_MAX_DAYS = 5.0


def _days_until(end_date: str | None) -> float | None:
    """Days from now until a market's resolution. None if unparseable."""
    if not end_date:
        return None
    try:
        dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - datetime.now(timezone.utc)).total_seconds() / 86400.0


def _is_near_term(end_date: str | None) -> bool:
    d = _days_until(end_date)
    return d is not None and d <= _FAST_MAX_DAYS


class FollowEngine:
    def __init__(self, db: Database, data_client: DataClient, cfg: ConfigStore, executor: Executor):
        self.db = db
        self.data = data_client
        self.cfg = cfg
        self.executor = executor
        self._autopilot_last_run: datetime | None = None

    # ── account math ─────────────────────────────────────────
    def account(self) -> dict:
        r = self.cfg.risk()
        open_pos = self.db.open_positions()
        deployed = sum(p["stake_usd"] for p in open_pos)
        cur_value = sum(p["shares"] * p["cur_price"] for p in open_pos)
        realized = self.db.realized_pnl_total()
        cash = r.bankroll_usd + realized - deployed
        unrealized = cur_value - deployed
        return {
            "bankroll": round(r.bankroll_usd, 2),
            "cash": round(cash, 2),
            "deployed": round(deployed, 2),
            "curValue": round(cur_value, 2),
            "realized": round(realized, 2),
            "unrealized": round(unrealized, 2),
            "equity": round(cash + cur_value, 2),
            "openCount": len(open_pos),
        }

    def _kill_active(self, r: RiskView) -> bool:
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        realized_today = self.db.realized_since(midnight.isoformat())
        return realized_today <= -abs(r.daily_loss_kill_pct) * r.bankroll_usd

    def _stake(self, follow: dict, cash: float, r: RiskView) -> float:
        cap = r.max_usd_per_position
        alloc = follow.get("allocation_usd")
        # Per-trader allocation, when set, overrides the global per-position cap.
        stake = min(cap, alloc) if alloc else cap
        return min(stake, cash)

    @staticmethod
    def _name_for(wallet: str, open_pos: list[dict]) -> str:
        for p in open_pos:
            if p["wallet"] == wallet:
                return p["name"]
        return wallet[:10]

    async def _sync_autopilot(self, ac: AutopilotView) -> dict:
        """Make the follow list track the current top-N traders. Only touches
        auto-added follows; anything you followed manually is left alone."""
        window = "MONTH" if ac.autopilot_rank == "pnl_30d" else "ALL"
        try:
            # data-api caps limit at 50; fetch that and rank client-side.
            rows = await self.data.leaderboard(window, 50, "PNL")
        except Exception as exc:  # noqa: BLE001
            log.warning("autopilot leaderboard fetch failed: %s", exc)
            return {"added": 0, "removed": 0, "error": True}

        if ac.autopilot_rank == "churn":
            # Fast mode: prefer traders holding the MOST soon-resolving positions,
            # so the book turns over quickly. Scan a bounded set and score by how
            # many near-term positions each holds.
            cand = [t for t in rows if t["volume"] >= ac.autopilot_min_volume]
            scored: list[tuple[int, dict]] = []
            checked = 0
            for t in cand:
                if checked >= 25:
                    break
                checked += 1
                try:
                    positions = await self.data.open_positions(t["wallet"], 30)
                except Exception:  # noqa: BLE001
                    continue
                near = sum(1 for p in positions if _is_near_term(p.get("endDate")))
                if near > 0:
                    scored.append((near, t))
            scored.sort(key=lambda x: x[0], reverse=True)
            targets = [t for _, t in scored[: ac.autopilot_count]]
        else:
            if ac.autopilot_rank == "roi":
                cand = [t for t in rows if t["volume"] >= ac.autopilot_min_volume]
                cand.sort(key=lambda t: t["roi"], reverse=True)
            else:
                cand = sorted(rows, key=lambda t: t["pnl"], reverse=True)

            # A copy bot can only act on traders who currently HOLD positions, so
            # follow the best-ranked candidates that are actually active.
            keepers: list[dict] = []
            for t in cand:
                if len(keepers) >= ac.autopilot_count:
                    break
                try:
                    if await self.data.open_positions(t["wallet"], 1):
                        keepers.append(t)
                except Exception:  # noqa: BLE001
                    continue
            targets = keepers

        target_wallets = {t["wallet"] for t in targets}

        added = removed = 0
        for t in targets:
            if not self.db.get_follow(t["wallet"]):
                self.db.add_follow(t["wallet"], t["name"], auto=True)
                self.db.log(
                    "engine",
                    f"Autopilot followed {t['name']} (top {ac.autopilot_count} by {ac.autopilot_rank})",
                    wallet=t["wallet"], name=t["name"],
                )
                added += 1
        for f in self.db.list_follows():
            if f.get("auto") and f["wallet"] not in target_wallets:
                self.db.remove_follow(f["wallet"])
                self.db.log(
                    "engine",
                    f"Autopilot unfollowed {f['name']} (left top {ac.autopilot_count})",
                    wallet=f["wallet"], name=f["name"],
                )
                removed += 1
        return {"added": added, "removed": removed, "targets": len(targets)}

    def _reject_reason(self, price: float, r: RiskView) -> str | None:
        if not (r.price_band_low <= price <= r.price_band_high):
            return f"price {price:.2f} outside band {r.price_band_low:.2f}–{r.price_band_high:.2f}"
        if self.db.count_open() >= r.max_open_positions:
            return f"portfolio full ({r.max_open_positions} open)"
        return None

    # ── the tick ─────────────────────────────────────────────
    async def tick(self) -> dict:
        # Autopilot first: refresh the follow list to the current top-N, so the
        # copy pass below acts on an up-to-date set. Throttled — the set changes
        # slowly and each sync scans many traders.
        ac = self.cfg.autopilot()
        autopilot = None
        if ac.autopilot_enabled:
            now = datetime.now(timezone.utc)
            due = (
                self._autopilot_last_run is None
                or (now - self._autopilot_last_run).total_seconds() >= _AUTOPILOT_SYNC_SECONDS
            )
            if due:
                autopilot = await self._sync_autopilot(ac)
                self._autopilot_last_run = now

        follows = {f["wallet"]: f for f in self.db.list_follows(active_only=True)}
        open_pos = self.db.open_positions()

        # Poll every wallet we either follow OR still hold a copy of, so
        # unfollowing a trader doesn't orphan open positions (they keep marking
        # and exiting); follows only govern NEW entries.
        wallets = set(follows) | {p["wallet"] for p in open_pos}
        if not wallets:
            return {"status": "idle", "reason": "no active follows", "opened": 0, "closed": 0}

        r = self.cfg.risk()
        # Paused (or the daily-loss kill) stops NEW entries but never blocks
        # marking or exiting positions we already hold.
        block_entries = r.engine_paused or self._kill_active(r)
        # Fast mode only copies soon-resolving positions (quick turnover).
        fast_mode = ac.autopilot_enabled and ac.autopilot_rank == "churn"
        opened = closed = marked = errors = 0

        for wallet in wallets:
            follow = follows.get(wallet)
            is_following = follow is not None
            name = follow["name"] if follow else self._name_for(wallet, open_pos)
            try:
                trader_positions = await self.data.open_positions(wallet, max_positions=50)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                log.warning("positions fetch failed for %s: %s", name, exc)
                continue

            current_assets = {p["asset"] for p in trader_positions if p.get("asset")}

            # ── Exits: our open copies of this trader they no longer hold ──
            for pos in self.db.open_positions():
                if pos["wallet"] == wallet and pos["asset"] not in current_assets:
                    self.executor.close_copy(self.db, pos, pos["cur_price"])
                    closed += 1

            # ── Entries / marks ──
            for p in trader_positions:
                asset = p.get("asset")
                if not asset:
                    continue
                p["_wallet"] = wallet
                existing = self.db.open_position(wallet, asset)
                if existing:
                    self.db.mark_position(existing["id"], float(p["curPrice"]))
                    marked += 1
                    continue

                # Only followed traders generate new copies.
                if not is_following:
                    continue

                newly = not self.db.has_seen(wallet, asset)
                price = float(p["curPrice"])
                reason = self._reject_reason(price, r)
                if reason is None and block_entries:
                    reason = "engine paused" if r.engine_paused else "daily-loss kill switch active"
                if reason is None and fast_mode and not _is_near_term(p.get("endDate")):
                    reason = f"resolves >{int(_FAST_MAX_DAYS)}d out (fast mode)"

                if reason is None:
                    cash = self.account()["cash"]
                    stake = self._stake(follow, cash, r)
                    if stake < 1:
                        if newly:
                            self.db.log("skip", "insufficient cash", wallet=wallet, name=name,
                                        title=p["title"], outcome=p["outcome"])
                    else:
                        self.executor.open_copy(self.db, p, name, stake)
                        opened += 1
                elif newly:
                    self.db.log("skip", reason, wallet=wallet, name=name,
                                title=p["title"], outcome=p["outcome"])

                self.db.mark_seen(wallet, asset)

        summary = {
            "status": "ok",
            "at": datetime.now(timezone.utc).isoformat(),
            "follows": len(follows),
            "opened": opened,
            "closed": closed,
            "marked": marked,
            "errors": errors,
            "paused": r.engine_paused,
            "killSwitch": self._kill_active(r),
            "autopilot": autopilot,
        }
        if opened or closed:
            log.info("tick: +%d opened, -%d closed (%d marked)", opened, closed, marked)
        return summary
