"""Read-only Polymarket public data-api client.

Ported from the original scanner.py, made async (httpx) so it fits FastAPI.
Places NO trades and needs NO keys. Everything here is public data:
the leaderboard and each wallet's open positions.

Note: this data-api is geoblocked from some cloud hosts. Run the backend on
your own machine or a small VPS in an allowed region.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

# Polymarket time-window codes -> friendly labels used by the dashboard
WINDOWS = {"ALL": "all_time", "MONTH": "last_30d"}


def _display_name(user_name: str | None, wallet: str) -> str:
    """Some accounts have no username (the API returns a raw address/id). Fall
    back to a short 0x1234…abcd form so the UI never shows a 40-char blob."""
    name = (user_name or "").strip()
    if not name or (name.startswith("0x") and len(name) > 16):
        return f"{wallet[:6]}…{wallet[-4:]}" if len(wallet) >= 10 else (name or "anon")
    return name


class DataClient:
    def __init__(self, base_url: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "copybot-scanner/1.0"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None, retries: int = 3) -> Any:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                r = await self._client.get(url, params=params)
                r.raise_for_status()
                return r.json()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < retries - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    # ── Leaderboard ──────────────────────────────────────────
    async def leaderboard(self, window: str, limit: int, order_by: str = "PNL") -> list[dict]:
        """Top traders for a window. order_by: PNL (profit) or VOLUME."""
        rows = await self._get(
            "/v1/leaderboard",
            params={
                "category": "OVERALL",
                "timePeriod": window,      # ALL or MONTH
                "orderBy": order_by,
                "limit": limit,
            },
        )
        traders = []
        for row in rows or []:
            pnl = float(row.get("pnl", 0) or 0)
            vol = float(row.get("vol", 0) or 0)
            wallet = row.get("proxyWallet", "") or ""
            traders.append({
                "rank": int(row.get("rank", 0)),
                "name": _display_name(row.get("userName"), wallet),
                "wallet": wallet,
                "pnl": pnl,
                "volume": vol,
                "roi": round(pnl / vol, 4) if vol else 0.0,
                "profileImage": row.get("profileImage") or "",
            })
        return traders

    # ── Positions ────────────────────────────────────────────
    async def open_positions(self, wallet: str, max_positions: int = 6) -> list[dict]:
        """Open positions for a wallet, largest first.

        'Open' = current price strictly between 0 and 1 (not yet settled).
        """
        rows = await self._get(
            "/positions",
            params={
                "user": wallet,
                "sizeThreshold": 1,
                "limit": 50,
                "sortBy": "CURRENT",
                "sortDirection": "DESC",
            },
        )
        out = []
        for p in rows or []:
            cur = float(p.get("curPrice", 0) or 0)
            if not (0 < cur < 1):  # skip settled / redeemable rows
                continue
            out.append({
                "title": p.get("title", ""),
                "outcome": p.get("outcome", ""),
                "value": round(float(p.get("currentValue", 0) or 0), 2),
                "avgPrice": round(float(p.get("avgPrice", 0) or 0), 4),
                "curPrice": round(cur, 4),
                "pnlPct": round(float(p.get("percentPnl", 0) or 0), 2),
                "slug": p.get("slug", ""),
                "eventSlug": p.get("eventSlug", ""),  # league-team-team-date; used to match on Polymarket US
                "conditionId": p.get("conditionId", ""),
                "asset": p.get("asset", ""),  # ERC1155 token id — needed to trade this outcome
                "endDate": p.get("endDate", ""),  # when the market resolves (for Fast/churn mode)
            })
            if len(out) >= max_positions:
                break
        return out

    # ── Combined snapshot (leaderboard + positions) ──────────
    async def snapshot(self, top: int, positions_per_trader: int = 6) -> dict:
        from datetime import datetime, timezone

        windows: dict[str, list[dict]] = {}
        for window, label in WINDOWS.items():
            traders = await self.leaderboard(window, top)
            # fetch each trader's open book concurrently, politely bounded
            sem = asyncio.Semaphore(4)

            async def with_positions(t: dict) -> dict:
                async with sem:
                    t["positions"] = await self.open_positions(
                        t["wallet"], positions_per_trader
                    )
                    t["openExposure"] = round(
                        sum(p["value"] for p in t["positions"]), 2
                    )
                    return t

            windows[label] = await asyncio.gather(
                *(with_positions(t) for t in traders)
            )

        return {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rankedBy": "profit",
            "topN": top,
            "windows": windows,
        }
