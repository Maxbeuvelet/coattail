"""Execution layer. The engine decides *what* to do; the executor *does* it.

Phase 2 ships PaperExecutor — fills are simulated at the trader's current price
and recorded in SQLite. Phase 4 will add a LiveExecutor with the same interface
that signs and submits real CLOB orders, so the engine never changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.db.repo import Database


class Executor(ABC):
    """Same surface for paper and live, so the engine is execution-agnostic."""

    mode: str

    @abstractmethod
    def open_copy(self, db: Database, trader_pos: dict, name: str, stake_usd: float) -> dict:
        """Buy `stake_usd` of the trader's outcome at its current price."""

    @abstractmethod
    def close_copy(self, db: Database, position: dict, exit_price: float) -> float:
        """Sell our whole position at `exit_price`. Returns realized P&L."""


class PaperExecutor(Executor):
    mode = "PAPER"

    def open_copy(self, db: Database, trader_pos: dict, name: str, stake_usd: float) -> dict:
        price = float(trader_pos["curPrice"])
        shares = round(stake_usd / price, 4) if price > 0 else 0.0
        position = {
            "wallet": trader_pos["_wallet"],
            "name": name,
            "asset": trader_pos["asset"],
            "condition_id": trader_pos.get("conditionId", ""),
            "title": trader_pos["title"],
            "outcome": trader_pos["outcome"],
            "entry_price": round(price, 4),
            "shares": shares,
            "stake_usd": round(stake_usd, 2),
        }
        pid = db.insert_position(position)
        position["id"] = pid
        db.log(
            "copy_open",
            f"Copied {name}: bought {shares:g} @ {price:.2f} (${stake_usd:,.0f})",
            wallet=position["wallet"],
            name=name,
            title=position["title"],
            outcome=position["outcome"],
            amount=round(stake_usd, 2),
        )
        return position

    def close_copy(self, db: Database, position: dict, exit_price: float) -> float:
        proceeds = position["shares"] * exit_price
        realized = round(proceeds - position["stake_usd"], 2)
        db.close_position(position["id"], round(exit_price, 4), realized)
        db.log(
            "copy_exit",
            f"Closed {position['name']} copy @ {exit_price:.2f} · "
            f"realized {'+' if realized >= 0 else ''}${realized:,.2f}",
            wallet=position["wallet"],
            name=position["name"],
            title=position["title"],
            outcome=position["outcome"],
            amount=realized,
        )
        return realized
