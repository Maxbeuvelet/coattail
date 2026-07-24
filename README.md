# Coattail

A Polymarket copy-trading bot. Finds the top traders, mirrors their trades into
your own book scaled to sizing **you** control, and shows everything on a
terminal-grade React dashboard. **Autopilot** can pick and follow the best active
traders for you, fully hands-off. Currently **paper trading** (simulated) —
prove the edge before risking real money.

> ⚠️ **Real money (later).** Prediction-market trading is high-risk; you can lose
> your whole stake. Live execution ships behind a hard safety gate
> (`LIVE_TRADING`, off by default). Not financial advice.

## Stack

- **Backend:** Python / FastAPI + SQLite. Polls Polymarket's public data-api,
  runs the follow engine, serves the dashboard.
- **Frontend:** React + Vite + TypeScript (CSS Modules, no framework).

## First-time setup (e.g. cloning at home)

Prereqs: **Python 3.11+**, **Node 20+**, git.

```bash
git clone <your-repo-url> coattail && cd coattail

# ── backend ──
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
cp .env.example .env          # then open .env and set OWNER_KEY (any random string)
cd ..

# ── frontend ──
cd frontend && npm install && cd ..
```

Then run it (see **Run it** below). The SQLite DB, `.env`, `node_modules`, and the
Python venv are **not** in git — they're created fresh per machine. Your paper
book starts empty; turn on Autopilot (Settings) or follow traders on Discover.

## Status

| Phase | What | Done |
|-------|------|------|
| 0 | Backend scaffold + read-only scanner API | ✅ |
| 1 | React dashboard (Discover/Following/Book/Activity/Settings) wired to the API | ✅ |
| 2 | Follow engine (entries/exits) + your book in SQLite | ✅ |
| 3 | Sizing + risk controls as dashboard settings | ✅ |
| 4 | Live CLOB execution behind the gate + small-cap test | ⬜ |

## Run it

**Easiest (Windows):** double-click / run `start.ps1` — it launches both halves
and opens the dashboard.

**Manual:**
```bash
# Terminal 1 — backend (engine runs automatically, ticks every 30s)
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev      # http://localhost:5173
```

## Share it publicly with a URL (Tailscale Funnel)

Give the app a **free, permanent, public HTTPS URL** anyone can open — while
keeping the controls yours. Visitors get a **read-only** dashboard; only requests
carrying your `OWNER_KEY` can change anything (enforced by the backend).

**One-time setup:**
1. Set `OWNER_KEY` in `backend/.env` (already generated for you — a random secret).
2. Install [Tailscale](https://tailscale.com/download) on this PC and sign in.
3. In the Tailscale admin console, enable **HTTPS certificates** and **Funnel**
   (Settings → Feature previews / DNS). The CLI will link you there if it's off.

**Each time you want it live:**
```powershell
# 1. Serve the app on your PC
./serve.ps1                 # runs on 0.0.0.0:8000

# 2. In a second terminal, expose it publicly
tailscale funnel 8000
```
Tailscale prints a public URL like `https://your-pc.tailXXXX.ts.net`.

- **Share that plain URL** with friends — they see a live, read-only dashboard.
- **Unlock your own control** by visiting `https://your-pc.tailXXXX.ts.net/?key=YOUR_OWNER_KEY`
  once on each of your devices. The key is saved locally and stripped from the
  address bar. (Don't share the `?key=` link — that grants control.)

The bot only runs while this PC is on with `serve.ps1` + `tailscale funnel`
running. Nothing lives in the cloud (the data-api is geoblocked there).

> Read-only protects the controls, but the dashboard itself is public to anyone
> with the URL. That's fine while it's paper. **Before enabling live trading**,
> the owner key alone isn't enough — we'd add proper login, since a public URL
> that moves real money is a different risk class.

## Access it from your phone / another device (same Wi-Fi, no tunnel)

`serve.ps1` builds the dashboard and runs the **whole app as one server** on your
network (`0.0.0.0:8000`). The backend serves the React app, so there's a single
URL — no separate frontend server.

- **Same Wi-Fi:** open `http://<this-pc-ip>:8000` on your phone. (Windows may
  need an inbound-firewall allow for port 8000 — see below.)
- **From anywhere (cellular, work):** put this PC on [Tailscale](https://tailscale.com),
  install Tailscale on your phone, and use the PC's `100.x.y.z` tailnet IP:
  `http://100.x.y.z:8000`. Private to your own devices; nothing is exposed to the
  public internet.

The bot only runs while this PC is on and `serve.ps1` is running — the geoblocked
data-api works from your home machine, which is why it lives here rather than in
the cloud.

Allow the port through Windows Firewall (run once, as admin) if your phone can't
connect on Wi-Fi:
```powershell
New-NetFirewallRule -DisplayName "copytrade 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

> No login yet — fine while it's **paper** (no money, no keys). Before enabling
> live trading, add authentication, since the dashboard would then move real funds.

## Autopilot (fully hands-off)

Turn on **Autopilot** in Settings and the bot picks the traders for you: each
sync it ranks the leaderboard (by ROI, all-time profit, or 30-day) and
auto-follows the top N traders that are **currently holding positions** (the
highest-ROI accounts are often flat, so it skips those), then copies their books
within your risk limits. It keeps the set in sync as the leaderboard moves and
never touches anyone you followed manually. Re-selection is throttled to every
few minutes.

## Running it as a paper trial (recommended before going live)

1. On **Discover**, follow a handful of traders whose ROI (not just raw profit)
   looks like a repeatable edge.
2. Set your sizing in **Settings** (bankroll, per-position cap) and let it run.
   The engine copies entries, mirrors exits, and marks to market every 30s.
3. Watch the **Performance** page — win rate, closed-trade count, average P&L,
   profit factor, and an equity curve over closed trades. That's the honest
   scoreboard (open marks bounce; closes are real). Judge it after ~100+ closed
   trades, not on day-to-day equity. **Activity** shows why it did or skipped
   each trade.
4. Only wire live execution (Phase 4) if the paper results show a real, repeatable
   edge after slippage.

**Start fresh:** stop the backend and delete `backend/copybot.sqlite*` to wipe
follows, book, and history. (It's gitignored.)

## Layout

```
backend/          FastAPI service (Python)
  app/
    main.py         entrypoint + lifespan
    config.py       env-driven settings; LIVE_TRADING gate lives here
    polymarket/     Polymarket API clients (read-only now; CLOB executor later)
    api/routes.py   /api/status /leaderboard /positions /snapshot
    services/       follow engine, sizing, executor (later phases)
    db/             SQLite models (later phases)
frontend/         React + Vite dashboard (later phase)
```

## Run the backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
cp .env.example .env          # then edit .env
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/health and http://127.0.0.1:8000/api/snapshot?top=10

## How the engine works (Phase 2)

A background loop ticks every `ENGINE_INTERVAL_SECONDS` (30s). Each tick, for
every followed trader — **and** every trader you still hold a copy of — it pulls
their open positions and diffs against your book:

- they hold something you don't → **open** a copy (if it passes the risk filters)
- you hold something they exited → **close** your copy, realize P&L
- you both hold it → **mark** your copy to their current price

Risk filters (price band, max positions, per-position cap, daily-loss kill) are
enforced before any open, and every decision — including skips, with the reason —
is written to the activity log. All simulated in paper mode; the executor is the
one piece Phase 4 swaps for live CLOB orders.

## Safety rails (baked in)

1. `LIVE_TRADING=false` by default — copies are simulated until you flip it.
2. Your private key lives only in `backend/.env` (gitignored). It never reaches
   the browser.
3. Backend-enforced caps: max USD per position, max open positions, daily-loss
   kill switch. Start tiny.
