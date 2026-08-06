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

    cash = 0.0
    try:
        for b in (c.account.balances() or {}).get("balances") or []:
            if b.get("currency") == "USD":
                cash += float(b.get("currentBalance") or 0)
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

        value = net * mark if mark else None
        rows.append({
            "slug": slug,
            "title": md.get("title") or slug,
            "outcome": md.get("outcome") or "",
            "team": ((md.get("team") or {}) or {}).get("name") or "",
            "eventSlug": md.get("eventSlug") or "",
            "contracts": net,
            "cost": round(cost, 2),
            "avgPrice": round(cost / net, 4) if net else None,
            "mark": round(mark, 4) if mark else None,
            "settlementPx": round(settle, 4) if settle else None,
            "value": round(value, 2) if value is not None else None,
            "unrealized": round(value - cost, 2) if value is not None else None,
            "realized": round(_val(p.get("realized")), 2),
            "expired": bool(p.get("expired")),
            # Max payout if this resolves YES — the number that matters on a
            # cheap longshot, where mark-to-market understates the outcome.
            "ifWins": round(net * 1.0, 2),
        })

    rows.sort(key=lambda r: -(r["cost"] or 0))
    invested = round(sum(r["cost"] for r in rows), 2)
    value = round(sum(r["value"] or 0 for r in rows), 2)
    return {
        "connected": True,
        "cash": round(cash, 2),
        "positionCount": len(rows),
        "invested": invested,
        "marketValue": value,
        "unrealized": round(value - invested, 2),
        "ifAllWin": round(sum(r["ifWins"] for r in rows), 2),
        "equity": round(cash + value, 2),
        "positions": rows,
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
