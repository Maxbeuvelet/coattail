"""FastAPI entrypoint for the Polymarket copy-trade bot backend.

Run (from the backend/ dir):
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.routes import router as api_router
from app.config import get_settings
from app.db.repo import Database
from app.polymarket.data_client import DataClient
from app.polymarket.us_pricing import US_FEE_RATE
from app.services.config_store import ConfigStore
from app.services.engine import FollowEngine
from app.services.executor import LiveExecutor, PaperExecutor
from app.services.scheduler import EngineScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("copybot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.data_client = DataClient(settings.data_api)
    app.state.db = Database(settings.db_path)
    # Rebook the US shadow's closed trades under the current fee model, so a fee
    # change (e.g. the per-share → percent-of-notional fix) scrubs old values
    # in place — no need to clear the book.
    fixed = app.state.db.recompute_us_realized(US_FEE_RATE)
    if fixed:
        log.info("Recomputed US-shadow P&L on %d closed trades (fee=%.3f)", fixed, US_FEE_RATE)
    fixed_v2 = app.state.db.recompute_us2_realized(US_FEE_RATE)
    if fixed_v2:
        log.info("Recomputed US-shadow-v2 P&L on %d closed trades (fee=%.3f)", fixed_v2, US_FEE_RATE)
    app.state.config_store = ConfigStore(app.state.db, settings)

    # Paper by default. Live execution requires LIVE_TRADING *and* working
    # Polymarket US credentials; if the executor cannot be built we fall back to
    # paper rather than starting up in a half-armed state.
    executor: PaperExecutor | LiveExecutor = PaperExecutor()
    if settings.live_trading:
        try:
            executor = LiveExecutor(
                settings.polymarket_key_id,
                settings.polymarket_secret_key,
                max_usd_per_order=settings.live_max_usd_per_order,
                slippage_bips=settings.live_slippage_bips,
                dry_run=settings.live_dry_run,
            )
            log.warning(
                "LIVE execution armed — Polymarket US, max $%.2f/order, %d bips slippage%s",
                settings.live_max_usd_per_order,
                settings.live_slippage_bips,
                ", DRY RUN (orders previewed, not sent)" if settings.live_dry_run else "",
            )
        except Exception as exc:  # noqa: BLE001
            log.error("LIVE_TRADING is on but the live executor could not start: %s", exc)
            log.error("Falling back to PAPER. No real orders will be placed.")
            executor = PaperExecutor()

    app.state.engine = FollowEngine(
        app.state.db, app.state.data_client, app.state.config_store, executor
    )
    app.state.scheduler = EngineScheduler(app.state.engine, settings.engine_interval_seconds)

    mode = "LIVE 🔴" if executor.mode.startswith("LIVE") else "PAPER 🟢"
    log.warning("Copy-trade backend starting in %s mode (executor=%s)", mode, executor.mode)

    app.state.scheduler.start()
    try:
        yield
    finally:
        await app.state.scheduler.stop()
        await app.state.data_client.aclose()
        app.state.db.close()


app = FastAPI(title="Polymarket Copy-Trade Bot", version="0.2.0", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "copybot-backend", "version": "0.2.0"}


# ── Serve the built dashboard (single-server deploy) ─────────────────────────
# If frontend/dist exists (i.e. `npm run build` has been run), serve it so the
# whole app lives at one URL. API routes above take precedence; everything else
# falls back to the SPA's index.html for client-side routing.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if _DIST.is_dir():
    @app.get("/{full_path:path}")
    async def spa(full_path: str) -> FileResponse:
        candidate = (_DIST / full_path).resolve()
        # Serve a real static file when it exists and is inside dist…
        if full_path and str(candidate).startswith(str(_DIST)) and candidate.is_file():
            return FileResponse(candidate)
        # …otherwise hand back index.html so React Router can take over.
        return FileResponse(_DIST / "index.html")

    log.info("Serving dashboard from %s", _DIST)
else:
    log.info("No frontend build found at %s — API only (run `npm run build`)", _DIST)
