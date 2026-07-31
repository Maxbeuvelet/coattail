-- Copy-trade bot — paper/live book. SQLite.
-- One file, created on startup if absent. See app/db/repo.py.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Traders the user copies. Backend-owned (the dashboard reads/writes this).
CREATE TABLE IF NOT EXISTS follows (
  wallet         TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  allocation_usd REAL,               -- optional per-trader budget (Phase 3); null = use global cap
  active         INTEGER NOT NULL DEFAULT 1,
  auto           INTEGER NOT NULL DEFAULT 0,   -- 1 = added by Autopilot (auto-managed), 0 = you followed manually
  created_at     TEXT NOT NULL
);

-- Positions the bot holds on the user's behalf (simulated in paper mode).
CREATE TABLE IF NOT EXISTS positions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  wallet        TEXT NOT NULL,       -- trader we copied
  name          TEXT NOT NULL,       -- trader display name at copy time
  asset         TEXT NOT NULL,       -- ERC1155 token id (the specific outcome)
  condition_id  TEXT,
  title         TEXT NOT NULL,
  outcome       TEXT NOT NULL,
  entry_price   REAL NOT NULL,       -- our fill price (their curPrice at copy)
  shares        REAL NOT NULL,
  stake_usd     REAL NOT NULL,       -- cash deployed
  cur_price     REAL NOT NULL,       -- last mark
  status        TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'closed'
  opened_at     TEXT NOT NULL,
  exit_price    REAL,
  closed_at     TEXT,
  realized_pnl  REAL,
  -- "US shadow" comparison book: the same trade priced on Polymarket US.
  -- Null us_entry = no clean US match (excluded from the US curve).
  event_slug    TEXT,                -- league-team-team-date, for matching on US
  us_entry      REAL,                -- US fill price at open (same stake as the real copy)
  us_exit       REAL,                -- US price at close
  us_realized   REAL                 -- realized P&L had this been executed on US
);
CREATE INDEX IF NOT EXISTS idx_positions_open ON positions (status, wallet, asset);

-- Immutable audit log of every decision the engine makes.
CREATE TABLE IF NOT EXISTS activity (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       TEXT NOT NULL,
  kind     TEXT NOT NULL,            -- 'copy_open' | 'copy_exit' | 'skip' | 'engine'
  wallet   TEXT,
  name     TEXT,
  title    TEXT,
  outcome  TEXT,
  detail   TEXT,                     -- human-readable reason
  amount   REAL
);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity (ts DESC);

-- Runtime config overrides (risk limits edited from the dashboard). Anything
-- not present here falls back to the .env default. Applied live on next tick.
CREATE TABLE IF NOT EXISTS config (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Every (trader, asset) the engine has already evaluated, so a skipped
-- position isn't re-logged every tick and genuine new entries are detectable.
CREATE TABLE IF NOT EXISTS seen (
  wallet     TEXT NOT NULL,
  asset      TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  PRIMARY KEY (wallet, asset)
);
