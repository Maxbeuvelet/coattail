"""Execution layer. The engine decides *what* to do; the executor *does* it.

PaperExecutor simulates fills at the trader's current price on the international
book. LiveExecutor places real orders on Polymarket US — the venue a US trader
can actually use, and the one the US shadow book has been measuring all along.

The two are NOT symmetric, and that asymmetry is the whole point:

  • Paper fills at the international price, instantly, in unlimited size.
  • Live must first identify the *same market* on Polymarket US (see
    app.polymarket.us_pricing), then buy the YES or NO side of it at whatever
    the book actually offers.

So a live copy can only happen for trades the matcher confidently resolves.
Anything it cannot identify is skipped rather than approximated — roughly
three-quarters of what these traders do, on current measurements.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.db.repo import Database

log = logging.getLogger("copybot.executor")


class Executor(ABC):
    """Same surface for paper and live, so the engine is execution-agnostic."""

    mode: str

    #: Live venues need the US market resolved before an order can be placed.
    #: The engine checks this to decide whether to do that lookup up front.
    needs_us_market: bool = False

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
            "event_slug": trader_pos.get("eventSlug", ""),
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


class LiveOrderError(RuntimeError):
    """An order was rejected, unfilled, or refused by a local safety check."""


class SkipTrade(LiveOrderError):
    """A deliberate refusal, not a failure — already held, too small, no match.

    Separated so the tick's error count means "something went wrong" rather than
    "the engine declined to trade", which it does constantly and by design.
    """


class DryRunOrder(LiveOrderError):
    """The order validated against the venue but was deliberately not sent.

    Distinct from a failure: a preview that comes back clean means credentials,
    market matching, routing and order shape are all correct. No position is
    booked, because none exists.
    """


class LiveExecutor(Executor):
    """Places real money orders on Polymarket US via the official SDK.

    Deliberately conservative:

      • Every order is capped at `max_usd_per_order`, independently of whatever
        size the engine asks for. Sizing bugs upstream cannot spend more than
        this. The cap is enforced here, not trusted from the caller.
      • Orders are IOC market orders with an explicit slippage tolerance and
        `synchronousExecution`, so we learn the true fill price in the response
        instead of assuming one.
      • Unfilled or partially-filled orders raise rather than silently booking a
        position the exchange does not think we hold.
      • `dry_run` routes everything through the SDK's `preview` endpoint, which
        prices the order without submitting it. Use it to prove the whole path
        end to end before risking anything.

    The predicted price (what the shadow book expected) is recorded alongside
    the actual fill, because the gap between them is the one number no amount of
    shadow data can tell you.
    """

    mode = "LIVE"
    needs_us_market = True

    def __init__(
        self,
        key_id: str,
        secret_key: str,
        *,
        max_usd_per_order: float = 5.0,
        slippage_bips: int = 200,
        dry_run: bool = False,
    ):
        if not key_id or not secret_key:
            raise ValueError(
                "LiveExecutor needs POLYMARKET_KEY_ID and POLYMARKET_SECRET_KEY "
                "(create them at polymarket.us/developer)"
            )
        try:
            from polymarket_us import PolymarketUS
        except ImportError as exc:  # noqa: BLE001
            raise ImportError(
                "polymarket-us is not installed. It ships in requirements-live.txt: "
                "pip install -r backend/requirements-live.txt"
            ) from exc

        self.client = PolymarketUS(key_id=key_id, secret_key=secret_key)
        self.max_usd_per_order = float(max_usd_per_order)
        self.slippage_bips = int(slippage_bips)
        self.dry_run = bool(dry_run)
        self.mode = "LIVE-DRYRUN" if dry_run else "LIVE"

    # ── helpers ──────────────────────────────────────────────
    @staticmethod
    def _amount(v: float) -> dict:
        return {"value": f"{v:.2f}", "currency": "USD"}

    @staticmethod
    def _fill(resp: dict) -> tuple[float, float, float]:
        """(avg_price, shares, fees) from a CreateOrderResponse's executions."""
        shares = notional = fees = 0.0
        for ex in resp.get("executions") or []:
            if ex.get("type") in ("EXECUTION_TYPE_REJECTED", "EXECUTION_TYPE_CANCELED"):
                continue
            n = float(ex.get("lastShares") or 0)
            px = float((ex.get("lastPx") or {}).get("value") or 0)
            shares += n
            notional += n * px
            fees += float((ex.get("commissionNotionalCollected") or {}).get("value") or 0)
        return (notional / shares if shares else 0.0), shares, fees

    @staticmethod
    def _reject_reason(resp: dict) -> str | None:
        for ex in resp.get("executions") or []:
            if ex.get("orderRejectReason"):
                return f"{ex.get('orderRejectReason')}: {ex.get('text') or ''}".strip()
        return None

    def buying_power(self) -> float:
        """USD available to trade. Used as a preflight so an underfunded account
        fails with a clear message instead of a venue rejection."""
        try:
            bals = (self.client.account.balances() or {}).get("balances") or []
        except Exception as exc:  # noqa: BLE001
            log.debug("balance check failed: %s", exc)
            return float("nan")
        return sum(float(b.get("buyingPower") or 0) for b in bals if b.get("currency") == "USD")

    def _submit(self, params: dict) -> dict:
        """Send the order, or validate it without sending when dry_run."""
        if self.dry_run:
            order = (self.client.orders.preview({"request": params}) or {}).get("order") or {}
            meta = order.get("marketMetadata") or {}
            team = (meta.get("team") or {}).get("name") or ""
            raise DryRunOrder(
                f"validated, not sent — {order.get('marketSlug')} "
                f"[{meta.get('title') or ''} · {team} · {meta.get('outcome') or ''}] "
                f"{order.get('intent')} {order.get('quantity')} @ "
                f"{(order.get('price') or {}).get('value')} → state {order.get('state')}"
            )
        return self.client.orders.create(params)

    # ── the Executor interface ───────────────────────────────
    def open_copy(self, db: Database, trader_pos: dict, name: str, stake_usd: float) -> dict:
        """Buy the matched Polymarket US market. The engine must have resolved it
        first and stashed it on the position under `_us`."""
        us = trader_pos.get("_us") or {}
        slug, buy_yes = us.get("slug"), us.get("buy_yes")
        if not slug or buy_yes is None:
            raise SkipTrade("no confidently matched Polymarket US market")

        # Defence in depth against buying the same US market twice. The engine
        # already dedupes on (wallet, asset), but two different international
        # titles can resolve to one US market, and any future bookkeeping gap
        # must not translate into duplicate real orders.
        if db.open_position_by_live_slug(slug):
            raise SkipTrade(f"already hold {slug} — not buying it twice")

        spend = min(float(stake_usd), self.max_usd_per_order)
        if spend < 1.0:
            raise SkipTrade(f"stake ${spend:.2f} below the $1 minimum")

        predicted = float(us.get("price") or 0)
        if predicted <= 0:
            raise LiveOrderError("no reference price for this market")

        # Marketable LIMIT rather than a true market order. The venue requires a
        # price anyway, and a limit gives a hard ceiling: we cross the spread to
        # take liquidity but can never pay more than `limit`. IOC means any
        # unfilled remainder is cancelled instead of resting on the book.
        #
        # `limit` is what WE pay per contract. Prices on the wire are always
        # quoted on the YES side, so a NO buy (BUY_SHORT) is a sale of YES and
        # its wire price is a MINIMUM of 1 - limit, not a maximum of limit.
        # Sending `limit` directly on a short caps the wrong side of the book.
        limit = predicted * (1 + self.slippage_bips / 10_000)
        limit = min(0.99, max(0.01, round(limit, 2)))  # 0.01 tick, valid range
        wire_price = limit if buy_yes else round(1.0 - limit, 2)
        quantity = int(spend // limit)                 # contracts are integers
        if quantity < 1:
            raise SkipTrade(
                f"${spend:.2f} buys less than one contract at {limit:.2f}"
            )
        cost = quantity * limit
        if cost > self.max_usd_per_order + 1e-9:
            raise LiveOrderError(f"cost ${cost:.2f} exceeds cap ${self.max_usd_per_order:.2f}")

        # Preflight the balance so an empty account gives a clear reason rather
        # than an opaque venue rejection. Skipped in dry run, which spends
        # nothing and whose whole purpose is to validate the path on an
        # unfunded account. NaN means the check itself failed — don't block on
        # that, let the venue decide.
        if not self.dry_run:
            bp = self.buying_power()
            if bp == bp and bp < cost:  # NaN != NaN
                raise SkipTrade(
                    f"insufficient buying power: ${bp:.2f} available, order needs ${cost:.2f}"
                )

        params = {
            "marketSlug": slug,
            # LONG buys the YES side of the proposition, SHORT buys the NO side.
            "intent": "ORDER_INTENT_BUY_LONG" if buy_yes else "ORDER_INTENT_BUY_SHORT",
            "type": "ORDER_TYPE_LIMIT",
            "price": self._amount(wire_price),
            "quantity": quantity,
            "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
            "synchronousExecution": True,
            "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
        }
        resp = self._submit(params)
        # Check FILLS FIRST. An IOC order that fills and then cancels its
        # remainder returns both a fill execution and a cancel execution, and the
        # cancel can carry a reject reason. Treating that as a rejection threw
        # away real, already-settled fills — money spent with no position booked,
        # which then let the next tick buy the same market again. Only a response
        # with zero filled shares is a rejection.
        fill_price, shares, fees = self._fill(resp)
        if shares <= 0 or fill_price <= 0:
            reason = self._reject_reason(resp) or "no fill (no liquidity at limit)"
            raise LiveOrderError(f"rejected: {reason}")
        if (reason := self._reject_reason(resp)):
            # Partial fill: we own what filled, the rest was cancelled. Book it.
            log.warning("partial fill on %s (%s) — booking %g shares", slug, reason, shares)

        # `fill_price` is the YES-side quote. On a short, our cash cost per
        # contract is 1 - that. Booking the raw quote overstated both the entry
        # price and the stake on every NO position.
        cost_per_contract = fill_price if buy_yes else (1.0 - fill_price)
        position = {
            "wallet": trader_pos["_wallet"],
            "name": name,
            "asset": trader_pos["asset"],
            "condition_id": trader_pos.get("conditionId", ""),
            "title": trader_pos["title"],
            "outcome": trader_pos["outcome"],
            "event_slug": trader_pos.get("eventSlug", ""),
            "entry_price": round(cost_per_contract, 4),
            "shares": round(shares, 4),
            "stake_usd": round(shares * cost_per_contract, 2),
        }
        pid = db.insert_position(position)
        position["id"] = pid
        # The measurement: what the shadow said it would cost vs what it did.
        db.record_live_fill(
            pid,
            order_id=str(resp.get("id") or ""),
            slug=slug,
            predicted=predicted or None,
            actual=round(cost_per_contract, 4),
            shares=round(shares, 4),
            fees=round(fees, 4),
            side="YES" if buy_yes else "NO",
        )
        # Compare like with like: `predicted` is what WE expected to pay, so the
        # comparison must use our cost, not the YES-side quote.
        slip = (cost_per_contract - predicted) if predicted else 0.0
        side = "YES" if buy_yes else "NO"
        db.log(
            "copy_open",
            f"LIVE {name}: bought {shares:g} {side} @ {cost_per_contract:.3f} "
            f"(${position['stake_usd']:,.2f}; expected {predicted:.3f}, slippage {slip:+.3f})",
            wallet=position["wallet"], name=name, title=position["title"],
            outcome=position["outcome"], amount=position["stake_usd"],
        )
        log.warning("LIVE FILL %s %s @ %.4f (predicted %.4f, slip %+.4f, fee %.4f)",
                    slug, side, cost_per_contract, predicted, slip, fees)
        return position

    def close_copy(self, db: Database, position: dict, exit_price: float) -> float:
        """Close the whole position in its market. `exit_price` is only the
        engine's expectation — the realized number comes from the actual fill."""
        slug = position.get("live_slug")
        if not slug:
            raise LiveOrderError(f"position {position['id']} has no US market slug to close")

        params = {
            "marketSlug": slug,
            "synchronousExecution": True,
            "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
            "slippageTolerance": {"bips": self.slippage_bips},
        }
        if self.dry_run:
            raise DryRunOrder(f"would close {slug} ({position.get('shares')} shares) — not sent")
        resp = self.client.orders.close_position(params)

        fill_price, shares, fees = self._fill(resp)
        if fill_price <= 0:
            # Nothing sold. Do NOT book a close at the engine's mark — that
            # would tell the local book we exited while the exchange still shows
            # the position, the same divergence that lost money on the entry
            # path. Leave it open and let the next tick retry; a market that has
            # already resolved is handled by settlement reconciliation instead.
            reason = self._reject_reason(resp) or "no execution returned"
            raise LiveOrderError(f"close of {slug} did not fill ({reason}) — left open")

        proceeds = position["shares"] * fill_price
        realized = round(proceeds - position["stake_usd"] - fees, 2)
        db.close_position(position["id"], round(fill_price, 4), realized)
        db.record_live_exit(position["id"], round(fill_price, 4), round(fees, 4))
        db.log(
            "copy_exit",
            f"LIVE closed {position['name']} @ {fill_price:.3f} · "
            f"realized {'+' if realized >= 0 else ''}${realized:,.2f}",
            wallet=position["wallet"], name=position["name"], title=position["title"],
            outcome=position["outcome"], amount=realized,
        )
        return realized
