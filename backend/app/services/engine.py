"""The follow engine.

Each tick: for every active followed trader, pull their current open positions
and diff against our book —
  • they hold something we don't  → maybe open a copy (subject to risk filters)
  • we hold something they exited  → close our copy, realize P&L
  • we both hold it                → mark our copy to their current price

Runs the same in paper and (Phase 4) live mode; only the Executor differs.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.db.repo import Database
from app.polymarket.data_client import DataClient
from app.polymarket.us_pricing import US_FEE_RATE, us_quotes
from app.services.config_store import AutopilotView, ConfigStore, RiskView
from app.services.executor import DryRunOrder, Executor, SkipTrade

log = logging.getLogger("copybot.engine")

# The 'US shadow' book prices each copied trade on Polymarket US too, so its
# equity curve can be compared against the (international-priced) real book.
# Each US price lookup is a couple of gateway calls, so cap how many *new*
# entries we price per tick to keep the hot path fast; exits are always priced.
_US_ENTRY_BUDGET_PER_TICK = 12

# Re-mark open shadowed positions on the US side each tick, in step with the
# international mark, so an eventual close compares two equally-fresh prices
# (not a stale local mark vs a fresh US fetch). Safety cap on gateway load.
_US_MARK_BUDGET_PER_TICK = 40

# US trading-cost estimate lives in us_pricing (shared with the US-book route).


# The leaderboard churns slowly; re-selecting the auto-follow set every few
# minutes is plenty and keeps the per-trader position lookups off the hot path.
_AUTOPILOT_SYNC_SECONDS = 300

# "Fast" (churn) mode: only follow/copy positions that resolve within this many
# days, so the book turns over quickly and closed trades accrue fast.
_FAST_MAX_DAYS = 5.0


class SkipReason:
    """Machine-readable codes for why a trade was declined.

    Free text is unanalysable — "trade skipped" tells you nothing later. Every
    decline carries one of these so the counterfactual book can be grouped by
    cause and each filter judged on its own record.
    """
    NO_US_MARKET = "NO_US_MARKET"                 # no confident Polymarket US match
    PRICE_OUTSIDE_BAND = "PRICE_OUTSIDE_BAND"     # outside the configured price band
    PORTFOLIO_FULL = "PORTFOLIO_FULL"             # max_open_positions reached
    ENGINE_PAUSED = "ENGINE_PAUSED"
    KILL_SWITCH = "KILL_SWITCH"                   # daily loss limit hit
    RESOLVES_TOO_FAR = "RESOLVES_TOO_FAR"         # fast mode, resolution too distant
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    ALREADY_HELD = "ALREADY_HELD"
    ORDER_FAILED = "ORDER_FAILED"                 # venue rejected or no fill
    DRY_RUN = "DRY_RUN"

    @staticmethod
    def classify(text: str) -> str:
        """Map an engine/executor message onto a code."""
        t = (text or "").lower()
        if "no matching" in t or "no confidently matched" in t:
            return SkipReason.NO_US_MARKET
        if "outside band" in t:
            return SkipReason.PRICE_OUTSIDE_BAND
        if "portfolio full" in t:
            return SkipReason.PORTFOLIO_FULL
        if "kill switch" in t:
            return SkipReason.KILL_SWITCH
        if "paused" in t:
            return SkipReason.ENGINE_PAUSED
        if "resolves" in t:
            return SkipReason.RESOLVES_TOO_FAR
        if "cash" in t or "buying power" in t or "minimum" in t or "one contract" in t:
            return SkipReason.INSUFFICIENT_CASH
        if "already hold" in t:
            return SkipReason.ALREADY_HELD
        if "dry run" in t or "not sent" in t:
            return SkipReason.DRY_RUN
        return SkipReason.ORDER_FAILED


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
        # Public Polymarket US gateway (no auth for reads) for the shadow book.
        self._us_client = httpx.AsyncClient(
            timeout=15.0, headers={"User-Agent": "coattail/1.0"}
        )

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

    def _kill_state(self, r: RiskView) -> tuple[bool, float, float | None]:
        """Daily-loss circuit breaker: (active, realized_today, limit_usd).

        The limit is a percentage of what the book was worth at the START of the
        UTC day, not of the original bankroll. Current equity already has today's
        closes baked in, so adding them back recovers the day-open value.

        Sizing compounds off equity, so a limit pinned to the starting bankroll
        gets proportionally tighter every winning day — at $100 bankroll and
        $1,440 equity it fired at 0.7% of the book, stopping the engine on
        ordinary days. Scaling it keeps the stop meaningful as the book grows.

        `limit` is None when the switch is disabled (pct <= 0). Without that
        guard the comparison reads `realized_today <= 0`, true from the first
        tick of every day, so "no daily limit" would mean "never open anything".
        """
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        realized_today = self.db.realized_since(midnight.isoformat())
        if r.daily_loss_kill_pct <= 0:
            return False, realized_today, None
        day_start_equity = max(self.account()["equity"] - realized_today, 0.0)
        limit = -abs(r.daily_loss_kill_pct) * day_start_equity
        return realized_today <= limit, realized_today, round(limit, 2)

    def _kill_active(self, r: RiskView) -> bool:
        return self._kill_state(r)[0]

    def _stake(self, follow: dict, cash: float, r: RiskView, equity: float) -> float:
        if r.size_mode == "equity_pct":
            # Compound: each bet is a % of current equity, so size grows as you
            # win and shrinks as you lose.
            stake = equity * r.size_pct
        else:
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

    # ── US shadow book ───────────────────────────────────────
    async def _reconcile_pending(self, max_age_s: int = 120) -> tuple[int, int]:
        """Resolve resting maker orders: (filled, cancelled).

        A passive order does not fill on placement, so the position is carried as
        'pending' until the exchange says otherwise. Anything still working after
        `max_age_s` is cancelled — by then the trade we were copying is stale,
        and a forgotten order could fill hours later into a market that has moved.
        """
        pend = self.db.pending_positions()
        if not pend:
            return 0, 0
        now = datetime.now(timezone.utc)
        filled = cancelled = 0
        for p in pend:
            oid = p.get("order_id")
            if not oid:
                self.db.drop_pending(p["id"]); continue
            st = await asyncio.to_thread(self.executor.order_state, oid)
            state = str((st or {}).get("state") or "")
            cum = float((st or {}).get("cumQuantity") or 0)
            if cum > 0:
                avg = float(((st or {}).get("avgPx") or {}).get("value") or 0)
                # Quotes are YES-side; a NO position costs 1 - avg per contract.
                cost = (1.0 - avg) if p.get("live_side") == "NO" else avg
                if cost > 0:
                    self.db.promote_pending(p["id"], round(cost, 4), cum, round(cum * cost, 2))
                    filled += 1
                    log.warning("maker order filled: %s %g @ %.3f", p["live_slug"], cum, cost)
                    continue
            if state in ("ORDER_STATE_CANCELED", "ORDER_STATE_REJECTED", "ORDER_STATE_EXPIRED"):
                self.db.drop_pending(p["id"]); cancelled += 1; continue
            try:
                age = (now - datetime.fromisoformat(p["order_placed_at"])).total_seconds()
            except Exception:  # noqa: BLE001
                age = max_age_s + 1
            if age > max_age_s:
                await asyncio.to_thread(self.executor.cancel, oid, p["live_slug"])
                self.db.drop_pending(p["id"]); cancelled += 1
                log.warning("maker order expired unfilled after %.0fs: %s", age, p["live_slug"])
        return filled, cancelled

    async def _reconcile_settled(self) -> int:
        """Close local positions whose Polymarket US market has already resolved.

        Sports markets settle on their own, often before the trader we copy ever
        exits. Without this the copy stays open in our book forever — the VPS
        still carries June baseball from exactly this gap — and the account's
        real cash would drift away from what the book claims.

        Settles at 1.0 or 0.0, which is what the venue actually paid.
        """
        live = [p for p in self.db.open_positions() if p.get("live_slug")]
        if not live:
            return 0
        closed = 0
        for pos in live:
            try:
                s = await asyncio.to_thread(
                    self.executor.client.markets.settlement, pos["live_slug"]
                )
            except Exception:  # noqa: BLE001
                continue  # not settled yet, or lookup failed — try again later
            val = (s or {}).get("settlement")
            if val is None:
                continue
            # Settlement is quoted on the YES side. A NO position pays out when
            # the market settles to 0, so its payout is the complement.
            yes = 1.0 if float(val) >= 0.5 else 0.0
            price = yes if pos.get("live_side") != "NO" else 1.0 - yes
            realized = round(pos["shares"] * price - pos["stake_usd"], 2)
            self.db.close_position(pos["id"], price, realized)
            self.db.record_live_exit(pos["id"], price, 0.0)
            self.db.log(
                "copy_exit",
                f"SETTLED {pos['name']} @ {price:.0f} · "
                f"realized {'+' if realized >= 0 else ''}${realized:,.2f}",
                wallet=pos["wallet"], name=pos["name"], title=pos["title"],
                outcome=pos["outcome"], amount=realized,
            )
            log.warning("settled %s at %.0f (realized %+.2f)", pos["live_slug"], price, realized)
            closed += 1
        return closed

    def _log_skip(self, reason_text: str, *, wallet: str, name: str, p: dict,
                  our_price: float | None = None) -> None:
        """Record a declined trade in both the audit log and the counterfactual
        book, so it can be judged later on what it would have done."""
        code = SkipReason.classify(reason_text)
        self.db.log("skip", reason_text, wallet=wallet, name=name,
                    title=p.get("title"), outcome=p.get("outcome"))
        try:
            self.db.record_skip(
                wallet=wallet, name=name, asset=p.get("asset") or "",
                title=p.get("title") or "", outcome=p.get("outcome") or "",
                event_slug=p.get("eventSlug"), reason=code, detail=reason_text[:200],
                whale_entry=float(p.get("avgPrice") or 0) or None,
                our_price=our_price if our_price is not None else (float(p.get("curPrice") or 0) or None),
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("skip record failed: %s", exc)

    async def _resolve_us_market(self, trader_pos: dict) -> dict | None:
        """Which Polymarket US market and side would express this trade, and at
        what price? Returns None when the matcher isn't confident — the same
        strictness the shadow book uses, now gating real money."""
        try:
            q = await us_quotes(
                self._us_client,
                trader_pos.get("eventSlug", ""),
                trader_pos["outcome"],
                trader_pos["title"],
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("US market resolve failed: %s", exc)
            return None
        if not q.slug or q.buy_yes is None or not q.strict:
            return None
        return {"slug": q.slug, "buy_yes": q.buy_yes, "price": q.strict, "market": q.market}

    async def _shadow_open(self, position: dict, trader_pos: dict) -> None:
        """Record what this trade would have cost on Polymarket US. Same stake as
        the real copy; only the fill price differs. No match → not shadowed.

        Both matchers are priced off one fetch: the legacy (event-only) match
        keeps the original curve running, the strict (market-aware) match feeds
        the v2 curve, and because they share the fetch the two are directly
        comparable at the same instant."""
        try:
            q = await us_quotes(
                self._us_client,
                trader_pos.get("eventSlug", ""),
                position["outcome"],
                position["title"],
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("US entry price lookup failed: %s", exc)
            return
        self.db.mark_us2_seen(position["id"])
        if q.legacy and q.legacy > 0:
            self.db.set_us_entry(position["id"], round(q.legacy, 4))
            self.db.mark_us(position["id"], round(q.legacy, 4))  # seed the mark at entry
        if q.strict and q.strict > 0:
            self.db.set_us2_entry(position["id"], round(q.strict, 4), q.market)
            self.db.mark_us2(position["id"], round(q.strict, 4))

    async def _shadow_mark(self, position: dict, trader_pos: dict) -> None:
        """Refresh the US marks for an open shadowed position, alongside the
        international mark, so the two exit prices are captured equally fresh."""
        try:
            q = await us_quotes(
                self._us_client,
                trader_pos.get("eventSlug", "") or position.get("event_slug", ""),
                position["outcome"],
                position["title"],
            )
        except Exception:  # noqa: BLE001
            return
        if q.legacy and q.legacy > 0:
            self.db.mark_us(position["id"], round(q.legacy, 4))
        if q.strict and q.strict > 0:
            self.db.mark_us2(position["id"], round(q.strict, 4))

    async def _shadow_close(self, pos: dict) -> None:
        """Close both US shadows at their LAST US mark — captured on the same
        cadence as the international mark, so the exits are equally fresh (a fair
        close). Falls back to a live fetch, then the copy's own exit, if never
        marked."""
        if not pos.get("us_entry") and not pos.get("us2_entry"):
            return
        legacy_cur, strict_cur = pos.get("us_cur"), pos.get("us2_cur")
        # One refetch covers whichever side is missing a mark.
        if (pos.get("us_entry") and not legacy_cur) or (pos.get("us2_entry") and not strict_cur):
            try:
                q = await us_quotes(
                    self._us_client, pos.get("event_slug", ""), pos["outcome"], pos["title"]
                )
                legacy_cur = legacy_cur or q.legacy
                strict_cur = strict_cur or q.strict
            except Exception:  # noqa: BLE001
                pass

        stake = pos["stake_usd"]
        fee = stake * US_FEE_RATE  # round-trip US trading cost (estimate)
        for entry, cur, setter in (
            (pos.get("us_entry"), legacy_cur, self.db.set_us_exit),
            (pos.get("us2_entry"), strict_cur, self.db.set_us2_exit),
        ):
            if not entry or entry <= 0:
                continue
            exit_px = cur if cur and cur > 0 else pos["cur_price"]
            realized = round(stake / entry * exit_px - stake - fee, 2)
            setter(pos["id"], round(exit_px, 4), realized)

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
        # Recomputed after the pass for the summary, so the dashboard reflects
        # the state the closes in this tick just produced.
        # Fast mode only copies soon-resolving positions (quick turnover).
        fast_mode = ac.autopilot_enabled and ac.autopilot_rank == "churn"
        opened = closed = marked = errors = 0

        # Settled markets first: the venue has already paid, so clearing them
        # frees the book before we consider anything new. Counters must exist
        # before this runs.
        if getattr(self.executor, "needs_us_market", False):
            try:
                closed += await self._reconcile_settled()
            except Exception as exc:  # noqa: BLE001
                log.warning("settlement reconcile failed: %s", exc)
            # Then resting maker orders, so a fill counts as opened this tick
            # and an expired one frees its slot before we queue anything new.
            if getattr(self.executor, "maker", False):
                try:
                    f, x = await self._reconcile_pending()
                    opened += f
                    if f or x:
                        log.info("maker orders: %d filled, %d cancelled", f, x)
                except Exception as exc:  # noqa: BLE001
                    log.warning("pending reconcile failed: %s", exc)
        us_budget = _US_ENTRY_BUDGET_PER_TICK
        us_mark_budget = _US_MARK_BUDGET_PER_TICK

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

            # Counterfactual book: mark the ones the trader still holds, and
            # resolve the ones they have left. Same lifecycle as a real copy, so
            # taken and declined trades are measured the same way.
            live_px = {p["asset"]: float(p.get("curPrice") or 0)
                       for p in trader_positions if p.get("asset")}
            for sk in self.db.open_skips():
                if sk["wallet"] != wallet:
                    continue
                px = live_px.get(sk["asset"])
                if px:
                    self.db.mark_skip(sk["id"], px)
                elif sk["asset"] not in current_assets:
                    # They exited — close the counterfactual at its last mark,
                    # which is what we would have got had we been in it.
                    self.db.close_skip(sk["id"], float(sk["cur_price"] or sk["our_price"] or 0))

            # ── Exits: our open copies of this trader they no longer hold ──
            # When follow_exits is off we ignore the trader leaving and hold to
            # resolution instead. Measured on the live book: copies that followed
            # the trader out were held a median of 12 minutes and averaged -18.6%,
            # because a round trip pays two spread crossings and taker fees both
            # ways while the price barely moves. Copies held to settlement
            # averaged +9.1%. Settlement reconciliation closes them instead.
            for pos in (self.db.open_positions() if r.follow_exits else []):
                if pos["wallet"] == wallet and pos["asset"] not in current_assets:
                    try:
                        self.executor.close_copy(self.db, pos, pos["cur_price"])
                    except DryRunOrder as dry:
                        log.warning("DRY RUN close %s: %s", pos["title"][:40], dry)
                        continue
                    except Exception as exc:  # noqa: BLE001
                        # Leave it open and retry next tick. A close that failed
                        # must never take the whole tick down with it, and must
                        # never be booked as if it succeeded.
                        errors += 1
                        log.warning("close failed (%s): %s", pos["title"][:40], exc)
                        continue
                    closed += 1
                    await self._shadow_close(pos)

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
                    # Keep the US mark in step, so a later close is a fair compare.
                    if (existing.get("us_entry") or existing.get("us2_entry")) and us_mark_budget > 0:
                        us_mark_budget -= 1
                        await self._shadow_mark(existing, p)
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
                    acct = self.account()
                    stake = self._stake(follow, acct["cash"], r, acct["equity"])
                    if stake < 1:
                        if newly:
                            self._log_skip("insufficient cash", wallet=wallet, name=name, p=p)
                    else:
                        # Live venues can only copy a trade whose Polymarket US
                        # market we can identify with confidence. Resolve it
                        # first and skip cleanly when there is no match, rather
                        # than opening a position we cannot actually hold.
                        if getattr(self.executor, "needs_us_market", False):
                            p["_us"] = await self._resolve_us_market(p)
                            if not p["_us"]:
                                if newly:
                                    self._log_skip("no matching Polymarket US market",
                                                   wallet=wallet, name=name, p=p)
                                self.db.mark_seen(wallet, asset)
                                continue
                        try:
                            newpos = self.executor.open_copy(self.db, p, name, stake)
                        except DryRunOrder as dry:
                            # Not a failure: the venue accepted the order shape
                            # and we chose not to send it. No position exists.
                            log.warning("DRY RUN %s: %s", p.get("title", "")[:44], dry)
                            self._log_skip(f"dry run — {dry}", wallet=wallet, name=name, p=p)
                            self.db.mark_seen(wallet, asset)
                            continue
                        except SkipTrade as skip:
                            # Declined on purpose (already held, too small, no
                            # match). Routine, so it must not inflate the error
                            # count the dashboard shows.
                            if newly:
                                self._log_skip(str(skip), wallet=wallet, name=name, p=p)
                            self.db.mark_seen(wallet, asset)
                            continue
                        except Exception as exc:  # noqa: BLE001
                            errors += 1
                            log.warning("open failed (%s): %s", p.get("title", "")[:48], exc)
                            self._log_skip(f"order failed: {exc}", wallet=wallet, name=name, p=p)
                            self.db.mark_seen(wallet, asset)
                            continue
                        if newpos.get("pending"):
                            # Resting, not filled. It becomes a position only
                            # when the exchange fills it.
                            self.db.mark_seen(wallet, asset)
                            continue
                        opened += 1
                        if us_budget > 0:
                            us_budget -= 1
                            await self._shadow_open(newpos, p)
                elif newly:
                    self._log_skip(reason, wallet=wallet, name=name, p=p)

                self.db.mark_seen(wallet, asset)

        kill_on_now, realized_today, kill_limit = self._kill_state(r)
        summary = {
            "status": "ok",
            "at": datetime.now(timezone.utc).isoformat(),
            "follows": len(follows),
            "opened": opened,
            "closed": closed,
            "marked": marked,
            "errors": errors,
            "paused": r.engine_paused,
            "killSwitch": kill_on_now,
            # The live threshold in dollars (negative), so the limit is visible
            # rather than implied by a percentage of an unstated base.
            "killLimitUsd": kill_limit,
            "realizedToday": round(realized_today, 2),
            "autopilot": autopilot,
        }
        if opened or closed:
            log.info("tick: +%d opened, -%d closed (%d marked)", opened, closed, marked)
        return summary
