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
        return self._row(
            "SELECT * FROM positions WHERE status = 'open' AND wallet = ? AND asset = ?",
            (wallet, asset),
        )

    def count_open(self) -> int:
        row = self._row("SELECT COUNT(*) AS n FROM positions WHERE status = 'open'")
        return int(row["n"]) if row else 0

    def insert_position(self, p: dict[str, Any]) -> int:
        cur = self._exec(
            """INSERT INTO positions
               (wallet, name, asset, condition_id, title, outcome,
                entry_price, shares, stake_usd, cur_price, status, opened_at, event_slug)
               VALUES (?,?,?,?,?,?,?,?,?,?, 'open', ?, ?)""",
            (
                p["wallet"], p["name"], p["asset"], p.get("condition_id"), p["title"],
                p["outcome"], p["entry_price"], p["shares"], p["stake_usd"],
                p["entry_price"], _now(), p.get("event_slug"),
            ),
        )
        return int(cur.lastrowid)

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
