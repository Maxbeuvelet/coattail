"""Price an international whale bet on Polymarket US (public gateway).

Used by the 'US shadow' comparison book: for each trade Coattail copies at the
international price, we also look up what it would cost on Polymarket US, so the
two equity curves can be compared. Returns None when there's no clean US match
(different league prefix is fine; missing market or unalignable outcome is not).
"""
from __future__ import annotations

import json
import re

import httpx

GATEWAY = "https://gateway.polymarket.us"

# Estimated all-in Polymarket US trading cost, per share, round-trip. The
# entry-price gap (measured) is the dominant drag; this is an estimate on top so
# the US book reflects a realistic result. Tune when the real schedule is known.
US_FEE_PER_SHARE = 0.02

# key = teamA-teamB-YYYY-MM-DD  (ignores the differing league prefix: chi vs csl)
_KEY_RE = re.compile(r"-([a-z0-9]+)-([a-z0-9]+)-(\d{4}-\d{2}-\d{2})")
_WORD_RE = re.compile(r"[A-Z][a-zA-Z]{3,}")
_STOP = {"Will", "Half", "Over", "Under", "Spread", "Handicap"}


def _key(slug: str | None) -> str | None:
    m = _KEY_RE.search(slug or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _loads(s) -> list:
    if isinstance(s, list):
        return s
    try:
        return json.loads(s) if s else []
    except (json.JSONDecodeError, TypeError):
        return []


async def us_price(client: httpx.AsyncClient, event_slug: str, outcome: str, title: str) -> float | None:
    """Current Polymarket US price for the same game+outcome, or None if no match."""
    k = _key(event_slug)
    if not k:
        return None
    terms = [w for w in _WORD_RE.findall(title or "") if w not in _STOP]
    event = None
    for term in terms[:2]:
        try:
            r = await client.get(f"{GATEWAY}/v1/search", params={"query": term, "limit": 20}, timeout=12)
            data = r.json()
        except Exception:  # noqa: BLE001
            continue
        for e in data.get("events", []):
            if _key(e.get("slug")) == k:
                event = e
                break
        if event:
            break
    if not event:
        return None

    oc = (outcome or "").lower()
    for m in event.get("markets", []):
        outs = _loads(m.get("outcomes"))
        prs = _loads(m.get("outcomePrices"))
        for i, o in enumerate(outs):
            ol = str(o).lower()
            if ol and i < len(prs) and (oc in ol or ol in oc):
                try:
                    return float(prs[i])
                except (TypeError, ValueError):
                    pass
    return None
