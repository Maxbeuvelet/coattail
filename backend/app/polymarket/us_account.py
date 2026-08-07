"""Read-only view of the real Polymarket US account.

Deliberately sourced from the venue rather than our own SQLite book. The local
book can be wrong — it was, on the first live run, when filled orders were
misread as rejections and never recorded — and when real money is involved the
exchange is the authority, not our bookkeeping.

So this shows every position the account actually holds, including ones the bot
never knew it opened and any placed by hand in the app.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("copybot.us_account")


def _val(amount: dict | None) -> float:
    try:
        return float((amount or {}).get("value") or 0)
    except (TypeError, ValueError):
        return 0.0


def _client(key_id: str, secret_key: str):
    from polymarket_us import PolymarketUS

    return PolymarketUS(key_id=key_id, secret_key=secret_key)


def _fetch(key_id: str, secret_key: str) -> dict:
    """Blocking fetch — run off the event loop by `live_book`."""
    c = _client(key_id, secret_key)

    # `currentBalance` is NOT spendable. Short positions post collateral, which
    # the venue holds as `marginRequirement`; what is actually free to trade is
    # `buyingPower`. Reporting the former as "cash" overstates what the bot can
    # deploy — with four shorts open, $25.03 of balance was $2.09 of buying power.
    cash = balance = reserved = 0.0
    try:
        for b in (c.account.balances() or {}).get("balances") or []:
            if b.get("currency") != "USD":
                continue
            balance += float(b.get("currentBalance") or 0)
            cash += float(b.get("buyingPower") or 0)
            reserved += float(b.get("marginRequirement") or 0)
    except Exception as exc:  # noqa: BLE001
        log.warning("balance fetch failed: %s", exc)

    try:
        raw = (c.portfolio.positions() or {}).get("positions") or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("positions fetch failed: %s", exc)
        raw = {}

    rows: list[dict] = []
    for slug, p in (raw.items() if isinstance(raw, dict) else []):
        net = float(p.get("netPosition") or 0)
        if net == 0:
            continue
        cost = _val(p.get("cost"))
        md = p.get("marketMetadata") or {}

        # Mark to what we could actually sell at (the bid), not the mid — the
        # same taker-side honesty the shadow book uses on entry.
        mark = settle = None
        try:
            data = (c.markets.bbo(slug) or {}).get("marketData") or {}
            bid, cur = _val(data.get("bestBid")), _val(data.get("currentPx"))
            mark = bid or cur or None
            settle = _val(data.get("settlementPx")) or None
        except Exception as exc:  # noqa: BLE001
            log.debug("bbo failed for %s: %s", slug, exc)

        # A negative netPosition is a SHORT — we hold the NO side. Quotes are
        # always YES-side, so a short contract is worth 1 - mark and pays out
        # when the market resolves NO. Marking it as net*mark makes the whole
        # position negative, which is not a price a position can have.
        qty = abs(net)
        is_short = net < 0
        our_mark = (1.0 - mark) if (mark is not None and is_short) else mark
        value = qty * our_mark if our_mark is not None else None
        rows.append({
            "slug": slug,
            "title": md.get("title") or slug,
            # The market's own label. Which side we hold is `short`, kept
            # separate so the UI doesn't end up rendering "NO No".
            "outcome": md.get("outcome") or "",
            "team": ((md.get("team") or {}) or {}).get("name") or "",
            "eventSlug": md.get("eventSlug") or "",
            "contracts": qty,
            "short": is_short,
            "cost": round(cost, 2),
            "avgPrice": round(cost / qty, 4) if qty else None,
            "mark": round(our_mark, 4) if our_mark is not None else None,
            "settlementPx": round(settle, 4) if settle else None,
            "value": round(value, 2) if value is not None else None,
            "unrealized": round(value - cost, 2) if value is not None else None,
            "realized": round(_val(p.get("realized")), 2),
            "expired": bool(p.get("expired")),
            # Max payout at resolution — the number that matters on a cheap
            # longshot, where mark-to-market understates the outcome.
            "ifWins": round(qty * 1.0, 2),
        })

    rows.sort(key=lambda r: -(r["cost"] or 0))
    invested = round(sum(r["cost"] for r in rows), 2)
    value = round(sum(r["value"] or 0 for r in rows), 2)

    # ── Settled trades, from the venue's own realized P&L ──
    # `afterPosition.realized` is what the exchange booked, so the curve does not
    # depend on our arithmetic (or on our book, which missed nine fills).
    settled: list[dict] = []
    try:
        for a in (c.portfolio.activities() or {}).get("activities") or []:
            if a.get("type") != "ACTIVITY_TYPE_POSITION_RESOLUTION":
                continue
            r = a.get("positionResolution") or {}
            before, after = r.get("beforePosition") or {}, r.get("afterPosition") or {}
            md = before.get("marketMetadata") or {}
            settled.append({
                "t": r.get("updateTime") or after.get("updateTime"),
                "slug": r.get("marketSlug") or "",
                "title": md.get("title") or r.get("marketSlug") or "",
                "outcome": md.get("outcome") or "",
                "contracts": float(before.get("netPosition") or 0),
                "cost": round(_val(before.get("cost")), 2),
                "payout": round(_val(before.get("cashValue")), 2),
                "realized": round(_val(after.get("realized")), 2),
            })
    except Exception as exc:  # noqa: BLE001
        log.warning("activity fetch failed: %s", exc)

    settled.sort(key=lambda s: s["t"] or "")
    realized_total = round(sum(s["realized"] for s in settled), 2)

    # Curve baseline: what the account would be worth with zero P&L, so the line
    # starts flat and every move on it is a settled result.
    equity = round(cash + value, 2)
    baseline = round(equity - realized_total, 2)
    cum = 0.0
    curve = [{"t": None, "equity": baseline, "realized": 0.0}]
    for s in settled:
        cum += s["realized"]
        curve.append({
            "t": s["t"],
            "equity": round(baseline + cum, 2),
            "realized": round(cum, 2),
        })

    wins = sum(1 for s in settled if s["realized"] > 0)
    losses = sum(1 for s in settled if s["realized"] < 0)
    return {
        "connected": True,
        # Spendable, not total. See the balance comment above.
        "cash": round(cash, 2),
        "balance": round(balance, 2),
        "reserved": round(reserved, 2),
        "positionCount": len(rows),
        "invested": invested,
        "marketValue": value,
        "unrealized": round(value - invested, 2),
        "ifAllWin": round(sum(r["ifWins"] for r in rows), 2),
        "equity": equity,
        "positions": rows,
        # Settled history — every resolution on the account, bot or manual.
        "realizedTotal": realized_total,
        "settledCount": len(settled),
        "wins": wins,
        "losses": losses,
        "winRate": round(wins / (wins + losses), 4) if (wins + losses) else None,
        "baseline": baseline,
        "equityCurve": curve,
        "settled": list(reversed(settled)),
    }


async def live_book(key_id: str, secret_key: str) -> dict:
    """Positions and cash as the exchange sees them. The SDK is synchronous, so
    it runs in a worker thread to keep the event loop free."""
    if not key_id or not secret_key:
        return {
            "connected": False,
            "reason": "No Polymarket US credentials configured "
                      "(POLYMARKET_KEY_ID / POLYMARKET_SECRET_KEY).",
            "positions": [],
        }
    try:
        return await asyncio.to_thread(_fetch, key_id, secret_key)
    except ImportError:
        return {"connected": False, "reason": "polymarket-us is not installed.", "positions": []}
    except Exception as exc:  # noqa: BLE001
        log.warning("live book fetch failed: %s", exc)
        return {"connected": False, "reason": f"{type(exc).__name__}: {exc}", "positions": []}
