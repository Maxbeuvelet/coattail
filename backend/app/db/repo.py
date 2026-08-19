"""SQLite repository. One connection, guarded by a lock (low write volume).

Kept deliberately small and explicit — no ORM. Every query is visible here so
the trading logic elsewhere reads clearly.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = Path(__file__).parent / "schema.sql"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
            self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was first created (CREATE TABLE
        IF NOT EXISTS won't touch an existing table). Safe to run every start."""
        have = {r["name"] for r in self._rows("PRAGMA table_info(positions)")}
        for col, decl in (
            ("event_slug", "TEXT"),
            ("us_entry", "REAL"),
            ("us_cur", "REAL"),
            ("us_exit", "REAL"),
            ("us_realized", "REAL"),
            # us2_* = the market-aware shadow. Kept alongside the original us_*
            # columns (rather than replacing them) so the two matchers can be
            # compared on the same trades going forward.
            ("us2_entry", "REAL"),
            ("us2_cur", "REAL"),
            ("us2_exit", "REAL"),
            ("us2_realized", "REAL"),
            ("us2_market", "TEXT"),
            # Set when a v2 lookup was attempted, matched or not — the honest
            # denominator for the v2 match rate.
            ("us2_seen", "INTEGER DEFAULT 0"),
            # ── live execution (Polymarket US) ──
            # live_predicted vs live_fill is THE measurement a live test buys:
            # how far real fills land from the price the shadow book expected.
            ("live_order_id", "TEXT"),
            ("live_slug", "TEXT"),
            ("live_side", "TEXT"),
            ("live_predicted", "REAL"),
            ("live_fill", "REAL"),
            ("live_shares", "REAL"),
            ("live_fees", "REAL"),
            ("live_exit_fill", "REAL"),
            ("live_exit_fees", "REAL"),
            # What the trader we copy actually paid, captured at copy time.
            # We buy at their CURRENT price, which is usually worse — median 7c
            # on a 50c contract. Without storing this we cannot test whether the
            # gap predicts the outcome.
            ("whale_entry", "REAL"),
            # Resting maker orders: the position exists before it is filled.
            ("order_id", "TEXT"),
            ("order_placed_at", "TEXT"),
            # ── maker shadow ──
            # What a PASSIVE order would have cost, and whether it would ever
            # have filled. The median US spread is 28% of mid, crossed twice,
            # which is larger than the strategy's whole edge — so whether a
            # resting order fills is the question that decides everything.
            ("maker_cost", "REAL"),      # our cost/contract if we rested
            ("maker_wire", "REAL"),      # the YES-side price we would rest at
            ("maker_filled", "INTEGER DEFAULT 0"),
            ("maker_checks", "INTEGER DEFAULT 0"),
            # ── attribution ──
            # The INTERNATIONAL price at the moment we copied, and at the moment
            # we exited. The paper bot books its P&L at these prices; the live
            # bot books at US prices. Storing both is the only way to say where
            # the difference between the two actually goes.
            ("intl_entry", "REAL"),
            ("intl_exit", "REAL"),
        ):
            if col not in have:
                self._exec(f"ALTER TABLE positions ADD COLUMN {col} {decl}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── low-level helpers ────────────────────────────────────
    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def _row(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    # ── follows ──────────────────────────────────────────────
    def list_follows(self, active_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM follows"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY created_at ASC"
        return self._rows(sql)

    def get_follow(self, wallet: str) -> dict | None:
        return self._row("SELECT * FROM follows WHERE wallet = ?", (wallet,))

    def add_follow(
        self, wallet: str, name: str, allocation_usd: float | None = None, auto: bool = False
    ) -> dict:
        # On conflict we keep the existing `auto` flag: a manual follow stays
        # manual even if Autopilot also targets it.
        self._exec(
            """INSERT INTO follows (wallet, name, allocation_usd, active, auto, created_at)
               VALUES (?, ?, ?, 1, ?, ?)
               ON CONFLICT(wallet) DO UPDATE SET name = excluded.name, active = 1""",
            (wallet, name, allocation_usd, 1 if auto else 0, _now()),
        )
        return self.get_follow(wallet)  # type: ignore[return-value]

    def reset_book(self) -> None:
        """Wipe follows, positions, activity and seen-state. Keeps config."""
        with self._lock:
            self._conn.executescript(
                "DELETE FROM positions; DELETE FROM activity; "
                "DELETE FROM seen; DELETE FROM follows;"
            )
            self._conn.commit()

    def remove_follow(self, wallet: str) -> None:
        self._exec("DELETE FROM follows WHERE wallet = ?", (wallet,))

    def set_allocation(self, wallet: str, allocation_usd: float | None) -> None:
        self._exec("UPDATE follows SET allocation_usd = ? WHERE wallet = ?", (allocation_usd, wallet))

    # ── positions ────────────────────────────────────────────
    def open_positions(self) -> list[dict]:
        return self._rows("SELECT * FROM positions WHERE status = 'open' ORDER BY opened_at DESC")

    def open_position(self, wallet: str, asset: str) -> dict | None:
        """Includes resting orders — otherwise we would re-queue the same trade
        on every tick while the first order is still working."""
        return self._row(
            """SELECT * FROM positions
               WHERE status IN ('open','pending') AND wallet = ? AND asset = ?""",
            (wallet, asset),
        )

    def count_open(self) -> int:
        row = self._row(
            "SELECT COUNT(*) AS n FROM positions WHERE status IN ('open','pending')"
        )
        return int(row["n"]) if row else 0

    def insert_position(self, p: dict[str, Any], status: str = "open") -> int:
        cur = self._exec(
            """INSERT INTO positions
               (wallet, name, asset, condition_id, title, outcome,
                entry_price, shares, stake_usd, cur_price, status, opened_at,
                event_slug, whale_entry, order_id, order_placed_at, intl_entry)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                p["wallet"], p["name"], p["asset"], p.get("condition_id"), p["title"],
                p["outcome"], p["entry_price"], p["shares"], p["stake_usd"],
                p["entry_price"], status, _now(), p.get("event_slug"),
                p.get("whale_entry"), p.get("order_id"), p.get("order_placed_at"),
                p.get("intl_entry"),
            ),
        )
        return int(cur.lastrowid)

    # ── resting (maker) orders ───────────────────────────────
    def pending_positions(self) -> list[dict]:
        return self._rows("SELECT * FROM positions WHERE status = 'pending'")

    def promote_pending(self, pid: int, entry: float, shares: float, stake: float) -> None:
        """A resting order filled — it is a real position now."""
        self._exec(
            """UPDATE positions
               SET status = 'open', entry_price = ?, cur_price = ?, shares = ?, stake_usd = ?
               WHERE id = ?""",
            (entry, entry, shares, stake, pid),
        )

    def drop_pending(self, pid: int) -> None:
        """Order cancelled or expired without filling — no position ever existed."""
        self._exec("DELETE FROM positions WHERE id = ? AND status = 'pending'", (pid,))

    # ── US shadow book (comparison: same trades priced on Polymarket US) ──
    def set_us_entry(self, position_id: int, us_entry: float) -> None:
        self._exec("UPDATE positions SET us_entry = ? WHERE id = ?", (us_entry, position_id))

    def recompute_us_realized(self, fee_rate: float) -> int:
        """Re-derive us_realized on every closed, US-matched trade from its stored
        prices and the given fee model. Idempotent; fixes trades whose P&L was
        booked under an old fee formula. Never touches the international book."""
        cur = self._exec(
            """UPDATE positions
               SET us_realized = ROUND(stake_usd / us_entry * us_exit
                                       - stake_usd - stake_usd * ?, 2)
               WHERE status = 'closed' AND us_entry IS NOT NULL
                 AND us_exit IS NOT NULL AND us_entry > 0""",
            (fee_rate,),
        )
        return cur.rowcount

    def mark_us(self, position_id: int, us_cur: float) -> None:
        """Update the last US mark — kept in step with the international mark so
        the eventual exit prices are equally fresh (a fair cross-venue close)."""
        self._exec("UPDATE positions SET us_cur = ? WHERE id = ?", (us_cur, position_id))

    def set_us_exit(self, position_id: int, us_exit: float, us_realized: float) -> None:
        self._exec(
            "UPDATE positions SET us_exit = ?, us_realized = ? WHERE id = ?",
            (us_exit, us_realized, position_id),
        )

    def us_positions(self) -> list[dict]:
        """Every trade that matched on Polymarket US (open + closed), open first,
        newest first — for the standalone US book."""
        return self._rows(
            """SELECT * FROM positions
               WHERE us_entry IS NOT NULL
               ORDER BY (status = 'open') DESC,
                        COALESCE(closed_at, opened_at) DESC"""
        )

    def us_realized_series(self) -> list[dict]:
        """Closed trades that had a US match, oldest-first — the US equity curve."""
        return self._rows(
            """SELECT closed_at, us_realized FROM positions
               WHERE status = 'closed' AND us_entry IS NOT NULL
                 AND us_exit IS NOT NULL AND closed_at IS NOT NULL
               ORDER BY closed_at ASC"""
        )

    def us_performance(self) -> dict:
        """US-shadow stats: how the same closed trades did at US prices, plus how
        many of all trades (open+closed) we could actually match on US."""
        realized = self._row(
            """SELECT
                 COUNT(*) AS n,
                 COALESCE(SUM(us_realized), 0) AS total,
                 COALESCE(SUM(realized_pnl), 0) AS own_total,  -- Coattail P&L on the SAME trades (fair head-to-head)
                 COALESCE(SUM(CASE WHEN us_realized > 0 THEN 1 ELSE 0 END), 0) AS wins,
                 COALESCE(SUM(CASE WHEN us_realized < 0 THEN 1 ELSE 0 END), 0) AS losses
               FROM positions
               WHERE status = 'closed' AND us_entry IS NOT NULL AND us_exit IS NOT NULL"""
        ) or {}
        # Denominator = trades OPENED since this feature went live (they carry an
        # event_slug; older trades predate it and never had a US lookup, so
        # counting them would crush the match rate with ineligible history).
        coverage = self._row(
            """SELECT
                 COUNT(*) AS total,
                 COALESCE(SUM(CASE WHEN us_entry IS NOT NULL THEN 1 ELSE 0 END), 0) AS matched
               FROM positions WHERE event_slug IS NOT NULL AND event_slug != ''"""
        ) or {}
        realized["matched"] = int(coverage.get("matched", 0) or 0)
        realized["totalTrades"] = int(coverage.get("total", 0) or 0)
        return realized

    # ── live execution bookkeeping ───────────────────────────
    def record_live_fill(
        self, position_id: int, *, order_id: str, slug: str, predicted: float | None,
        actual: float, shares: float, fees: float, side: str,
    ) -> None:
        """Store the real fill next to the price the shadow book predicted."""
        self._exec(
            """UPDATE positions
               SET live_order_id = ?, live_slug = ?, live_side = ?, live_predicted = ?,
                   live_fill = ?, live_shares = ?, live_fees = ?
               WHERE id = ?""",
            (order_id, slug, side, predicted, actual, shares, fees, position_id),
        )

    def record_live_exit(self, position_id: int, fill: float, fees: float) -> None:
        self._exec(
            "UPDATE positions SET live_exit_fill = ?, live_exit_fees = ? WHERE id = ?",
            (fill, fees, position_id),
        )

    def open_position_by_live_slug(self, slug: str) -> dict | None:
        """A position OR a resting order already in this Polymarket US market.

        Must include 'pending'. A maker order rests unfilled for up to 120s, and
        while it did not count here the engine happily queued another order in
        the same market on the next tick — and another. Sizes stacked well past
        the per-order cap (a $2 order became a $10.68 position) before anything
        filled. Every duplicate is real money.
        """
        return self._row(
            """SELECT * FROM positions
               WHERE status IN ('open','pending') AND live_slug = ?""",
            (slug,),
        )

    def live_fills(self, limit: int = 200) -> list[dict]:
        """Every live-executed trade, newest first — the slippage record."""
        return self._rows(
            """SELECT * FROM positions
               WHERE live_order_id IS NOT NULL
               ORDER BY opened_at DESC LIMIT ?""",
            (limit,),
        )

    # ── US shadow v2 (same idea, market-aware matcher — see us_pricing) ──
    def mark_us2_seen(self, position_id: int) -> None:
        """Record that a v2 lookup ran for this trade, whether or not it matched."""
        self._exec("UPDATE positions SET us2_seen = 1 WHERE id = ?", (position_id,))

    def set_us2_entry(self, position_id: int, us2_entry: float, market: str | None) -> None:
        self._exec(
            "UPDATE positions SET us2_entry = ?, us2_market = ? WHERE id = ?",
            (us2_entry, market, position_id),
        )

    def mark_us2(self, position_id: int, us2_cur: float) -> None:
        self._exec("UPDATE positions SET us2_cur = ? WHERE id = ?", (us2_cur, position_id))

    def set_us2_exit(self, position_id: int, us2_exit: float, us2_realized: float) -> None:
        self._exec(
            "UPDATE positions SET us2_exit = ?, us2_realized = ? WHERE id = ?",
            (us2_exit, us2_realized, position_id),
        )

    def recompute_us2_realized(self, fee_rate: float) -> int:
        cur = self._exec(
            """UPDATE positions
               SET us2_realized = ROUND(stake_usd / us2_entry * us2_exit
                                        - stake_usd - stake_usd * ?, 2)
               WHERE status = 'closed' AND us2_entry IS NOT NULL
                 AND us2_exit IS NOT NULL AND us2_entry > 0""",
            (fee_rate,),
        )
        return cur.rowcount

    def us2_positions(self) -> list[dict]:
        return self._rows(
            """SELECT * FROM positions
               WHERE us2_entry IS NOT NULL
               ORDER BY (status = 'open') DESC,
                        COALESCE(closed_at, opened_at) DESC"""
        )

    def us2_realized_series(self) -> list[dict]:
        return self._rows(
            """SELECT closed_at, us2_realized FROM positions
               WHERE status = 'closed' AND us2_entry IS NOT NULL
                 AND us2_exit IS NOT NULL AND closed_at IS NOT NULL
               ORDER BY closed_at ASC"""
        )

    def us2_performance(self) -> dict:
        realized = self._row(
            """SELECT
                 COUNT(*) AS n,
                 COALESCE(SUM(us2_realized), 0) AS total,
                 COALESCE(SUM(realized_pnl), 0) AS own_total,
                 COALESCE(SUM(CASE WHEN us2_realized > 0 THEN 1 ELSE 0 END), 0) AS wins,
                 COALESCE(SUM(CASE WHEN us2_realized < 0 THEN 1 ELSE 0 END), 0) AS losses
               FROM positions
               WHERE status = 'closed' AND us2_entry IS NOT NULL AND us2_exit IS NOT NULL"""
        ) or {}
        # Denominator = trades opened since the v2 matcher went live. Trades that
        # predate it never had a v2 lookup, so counting them would understate the
        # match rate. `us2_seen` marks a lookup was attempted.
        coverage = self._row(
            """SELECT
                 COUNT(*) AS total,
                 COALESCE(SUM(CASE WHEN us2_entry IS NOT NULL THEN 1 ELSE 0 END), 0) AS matched
               FROM positions WHERE us2_seen = 1"""
        ) or {}
        realized["matched"] = int(coverage.get("matched", 0) or 0)
        realized["totalTrades"] = int(coverage.get("total", 0) or 0)
        return realized

    def mark_position(self, position_id: int, cur_price: float) -> None:
        self._exec("UPDATE positions SET cur_price = ? WHERE id = ?", (cur_price, position_id))

    def close_position(self, position_id: int, exit_price: float, realized_pnl: float) -> None:
        self._exec(
            """UPDATE positions
               SET status = 'closed', exit_price = ?, cur_price = ?,
                   realized_pnl = ?, closed_at = ?
               WHERE id = ?""",
            (exit_price, exit_price, realized_pnl, _now(), position_id),
        )

    def closed_positions(self, limit: int = 100) -> list[dict]:
        return self._rows(
            "SELECT * FROM positions WHERE status = 'closed' ORDER BY closed_at DESC LIMIT ?",
            (limit,),
        )

    def realized_pnl_total(self) -> float:
        row = self._row(
            "SELECT COALESCE(SUM(realized_pnl), 0) AS s FROM positions WHERE status = 'closed'"
        )
        return float(row["s"]) if row else 0.0

    def performance(self) -> dict:
        """Aggregate stats over closed positions (realized trades)."""
        return self._row(
            """SELECT
                 COUNT(*) AS n,
                 COALESCE(SUM(realized_pnl), 0) AS total,
                 COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                 COALESCE(SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END), 0) AS losses,
                 COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END), 0) AS gross_win,
                 COALESCE(SUM(CASE WHEN realized_pnl < 0 THEN realized_pnl ELSE 0 END), 0) AS gross_loss,
                 COALESCE(MAX(realized_pnl), 0) AS best,
                 COALESCE(MIN(realized_pnl), 0) AS worst
               FROM positions WHERE status = 'closed'"""
        ) or {}

    def calibration(self) -> dict:
        """Does the shadow book actually predict what we pay?

        Every shadow-based plan — exit re-scoring, trader scanning, filter
        design — assumes this simulator reproduces reality. Nobody has checked.
        If predicted and actual diverge, every conclusion drawn from the shadow
        book is fiction, and that is worth knowing before another afternoon is
        spent on it.

        Compares the price the shadow book predicted against the fill we
        actually got, on the same trade.
        """
        return self._row(
            """SELECT
                 COUNT(*) AS n,
                 AVG(live_fill - live_predicted)              AS mean_err,
                 AVG(ABS(live_fill - live_predicted))         AS mean_abs_err,
                 AVG(CASE WHEN live_predicted > 0
                          THEN (live_fill - live_predicted) / live_predicted END) AS mean_pct_err,
                 SUM(CASE WHEN live_fill > live_predicted + 0.001 THEN 1 ELSE 0 END) AS paid_more,
                 SUM(CASE WHEN live_fill < live_predicted - 0.001 THEN 1 ELSE 0 END) AS paid_less,
                 SUM(CASE WHEN ABS(live_fill - live_predicted) <= 0.001 THEN 1 ELSE 0 END) AS exact,
                 MAX(ABS(live_fill - live_predicted))         AS worst_err,
                 AVG(live_predicted) AS avg_predicted,
                 AVG(live_fill)      AS avg_fill
               FROM positions
               WHERE live_predicted IS NOT NULL AND live_predicted > 0
                 AND live_fill IS NOT NULL AND live_fill > 0"""
        ) or {}

    def calibration_rows(self, limit: int = 40) -> list[dict]:
        """The individual comparisons, worst error first — so a bad average can
        be traced to specific trades rather than argued about."""
        return self._rows(
            """SELECT title, outcome, live_side, live_slug, live_predicted, live_fill,
                      (live_fill - live_predicted) AS err, stake_usd, realized_pnl, status
               FROM positions
               WHERE live_predicted IS NOT NULL AND live_predicted > 0
                 AND live_fill IS NOT NULL AND live_fill > 0
               ORDER BY ABS(live_fill - live_predicted) DESC LIMIT ?""",
            (limit,),
        )

    def set_intl_exit(self, pid: int, price: float) -> None:
        """The international price when we exited — what the paper book would
        have realised on the same trade."""
        self._exec("UPDATE positions SET intl_exit = ? WHERE id = ?", (price, pid))

    def attribution(self) -> dict:
        """Decompose the gap between the international result and ours.

        For each closed trade with both prices recorded:
          intl return  = (intl_exit - intl_entry) / intl_entry     what paper books
          our return   = (exit_price - entry_price) / entry_price  what we book
          entry drag   = (entry_price - intl_entry) / intl_entry   paying up to enter
          exit drag    = (intl_exit - exit_price) / intl_exit      getting less to exit
          fee drag     = fees / stake
        """
        return self._row(
            """SELECT
                 COUNT(*) AS n,
                 AVG((intl_exit - intl_entry) / intl_entry)            AS intl_return,
                 AVG((exit_price - entry_price) / entry_price)         AS our_return,
                 AVG((entry_price - intl_entry) / intl_entry)          AS entry_drag,
                 AVG((intl_exit - exit_price) / intl_exit)             AS exit_drag,
                 AVG((COALESCE(live_fees,0) + COALESCE(live_exit_fees,0)) / stake_usd) AS fee_drag,
                 AVG(intl_entry) AS avg_intl_entry,
                 AVG(entry_price) AS avg_our_entry
               FROM positions
               WHERE status = 'closed'
                 AND intl_entry > 0 AND intl_exit > 0
                 AND entry_price > 0 AND exit_price > 0 AND stake_usd > 0"""
        ) or {}

    def set_maker_shadow(self, pid: int, cost: float, wire: float) -> None:
        self._exec(
            "UPDATE positions SET maker_cost = ?, maker_wire = ? WHERE id = ?",
            (cost, wire, pid),
        )

    def maker_check(self, pid: int, filled: bool) -> None:
        """One observation of whether a resting order would have been hit."""
        self._exec(
            """UPDATE positions
               SET maker_checks = COALESCE(maker_checks, 0) + 1,
                   maker_filled = CASE WHEN ? THEN 1 ELSE COALESCE(maker_filled, 0) END
               WHERE id = ?""",
            (1 if filled else 0, pid),
        )

    def maker_stats(self) -> dict:
        """Would resting instead of crossing have been better, and how often
        would it actually have filled?"""
        return self._row(
            """SELECT
                 COUNT(*) AS n,
                 SUM(maker_filled) AS filled,
                 AVG(entry_price - maker_cost) AS avg_saving,
                 AVG(CASE WHEN maker_cost > 0
                          THEN (entry_price - maker_cost) / entry_price END) AS avg_saving_pct,
                 AVG(maker_checks) AS avg_checks,
                 AVG(CASE WHEN maker_filled = 1 THEN realized_pnl / stake_usd END) AS filled_return,
                 AVG(realized_pnl / stake_usd) AS all_return
               FROM positions
               WHERE maker_cost IS NOT NULL AND entry_price > 0"""
        ) or {}

    def match_split(self) -> list[dict]:
        """Do trades that EXIST on Polymarket US perform differently?

        The live bot can only take the ~34% of trades that match a US market. If
        that subset is systematically worse than the rest, it explains the live
        bot's 10-point win-rate gap without any execution problem at all.

        Compares return ON STAKE, not dollars — the paper book compounds, so a
        late trade is worth thousands of times an early one and dollar sums are
        meaningless across the run. Restricted to us2_seen, i.e. trades where a
        US lookup was actually attempted, so pre-matcher history is excluded.
        """
        return self._rows(
            """SELECT
                 CASE WHEN us2_entry IS NOT NULL THEN 'on_us' ELSE 'not_on_us' END AS grp,
                 COUNT(*) AS n,
                 AVG(realized_pnl / stake_usd) AS avg_return,
                 AVG(CASE WHEN realized_pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
                 AVG(entry_price) AS avg_entry,
                 AVG(CASE WHEN whale_entry > 0
                          THEN (entry_price - whale_entry) / whale_entry END) AS avg_gap
               FROM positions
               WHERE status = 'closed' AND stake_usd > 0 AND us2_seen = 1
               GROUP BY grp"""
        )

    def whale_gap(self) -> dict:
        """How much worse our entry was than the trader's own, on trades where
        we captured both. This is the single biggest measured drag: we buy at
        their CURRENT price, after the move that made the position worth having."""
        return self._row(
            """SELECT
                 COUNT(*) AS n,
                 AVG(entry_price - whale_entry) AS avg_gap,
                 AVG(CASE WHEN whale_entry > 0
                          THEN (entry_price - whale_entry) / whale_entry END) AS avg_pct,
                 SUM(CASE WHEN entry_price > whale_entry THEN 1 ELSE 0 END) AS worse
               FROM positions
               WHERE whale_entry IS NOT NULL AND whale_entry > 0"""
        ) or {}

    def realized_series(self) -> list[dict]:
        """Closed trades oldest-first — for the cumulative equity curve."""
        return self._rows(
            """SELECT closed_at, realized_pnl FROM positions
               WHERE status = 'closed' AND closed_at IS NOT NULL
               ORDER BY closed_at ASC"""
        )

    def realized_since(self, iso: str) -> float:
        row = self._row(
            """SELECT COALESCE(SUM(realized_pnl), 0) AS s FROM positions
               WHERE status = 'closed' AND closed_at >= ?""",
            (iso,),
        )
        return float(row["s"]) if row else 0.0

    # ── counterfactual book (trades we declined) ─────────────
    def record_skip(
        self, *, wallet: str, name: str, asset: str, title: str, outcome: str,
        event_slug: str | None, reason: str, detail: str,
        whale_entry: float | None, our_price: float | None,
    ) -> None:
        """Log a declined trade and start tracking what it would have done.

        One row per (wallet, asset) — the engine re-evaluates the same position
        every tick, and re-logging it would flood the table and bias any average
        toward long-held positions.
        """
        if self._row(
            "SELECT 1 FROM skipped WHERE wallet = ? AND asset = ? AND status = 'open'",
            (wallet, asset),
        ):
            return
        self._exec(
            """INSERT INTO skipped
               (ts, wallet, name, asset, title, outcome, event_slug, reason, detail,
                whale_entry, our_price, cur_price, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'open')""",
            (_now(), wallet, name, asset, title, outcome, event_slug, reason, detail,
             whale_entry, our_price, our_price),
        )

    def open_skips(self) -> list[dict]:
        return self._rows("SELECT * FROM skipped WHERE status = 'open'")

    def mark_skip(self, skip_id: int, cur_price: float) -> None:
        self._exec("UPDATE skipped SET cur_price = ? WHERE id = ?", (cur_price, skip_id))

    def close_skip(self, skip_id: int, exit_price: float) -> None:
        """Resolve a counterfactual at the same moment the real bot would have
        exited — when the trader drops the position."""
        self._exec(
            """UPDATE skipped
               SET status = 'closed', exit_price = ?, closed_at = ?,
                   hypo_return = CASE WHEN our_price > 0
                                      THEN (? - our_price) / our_price END
               WHERE id = ?""",
            (exit_price, _now(), exit_price, skip_id),
        )

    def skip_stats(self) -> list[dict]:
        """Per-reason counterfactual performance — did declining actually help?"""
        return self._rows(
            """SELECT reason,
                      COUNT(*) AS n,
                      SUM(status = 'closed') AS resolved,
                      AVG(CASE WHEN status = 'closed' THEN hypo_return END) AS avg_return,
                      AVG(CASE WHEN status = 'closed' AND hypo_return > 0 THEN 1.0
                               WHEN status = 'closed' THEN 0.0 END) AS win_rate,
                      AVG(our_price - whale_entry) AS avg_gap
               FROM skipped
               GROUP BY reason
               ORDER BY n DESC"""
        )

    # ── activity ─────────────────────────────────────────────
    def log(
        self,
        kind: str,
        detail: str,
        *,
        wallet: str | None = None,
        name: str | None = None,
        title: str | None = None,
        outcome: str | None = None,
        amount: float | None = None,
    ) -> None:
        self._exec(
            """INSERT INTO activity (ts, kind, wallet, name, title, outcome, detail, amount)
               VALUES (?,?,?,?,?,?,?,?)""",
            (_now(), kind, wallet, name, title, outcome, detail, amount),
        )

    def recent_activity(self, limit: int = 100) -> list[dict]:
        return self._rows("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))

    # ── config ───────────────────────────────────────────────
    def get_all_config(self) -> list[dict]:
        return self._rows("SELECT key, value FROM config")

    def set_config(self, key: str, value: str) -> None:
        self._exec(
            """INSERT INTO config (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )

    # ── seen ─────────────────────────────────────────────────
    def has_seen(self, wallet: str, asset: str) -> bool:
        return self._row("SELECT 1 FROM seen WHERE wallet = ? AND asset = ?", (wallet, asset)) is not None

    def mark_seen(self, wallet: str, asset: str) -> None:
        self._exec(
            "INSERT OR IGNORE INTO seen (wallet, asset, first_seen) VALUES (?,?,?)",
            (wallet, asset, _now()),
        )
