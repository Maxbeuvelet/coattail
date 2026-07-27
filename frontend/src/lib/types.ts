/** Shapes mirrored from the FastAPI backend (app/polymarket/data_client.py). */

export type LeaderWindow = 'ALL' | 'MONTH'
export type OrderBy = 'PNL' | 'VOLUME'
export type WindowKey = 'all_time' | 'last_30d'

export interface Position {
  title: string
  outcome: string
  value: number
  avgPrice: number
  curPrice: number
  pnlPct: number
  slug: string
  conditionId: string
  asset: string
}

export interface Trader {
  rank: number
  name: string
  wallet: string
  pnl: number
  volume: number
  roi: number
  profileImage: string
  positions: Position[]
  openExposure: number
}

export interface Snapshot {
  generatedAt: string
  rankedBy: string
  topN: number
  windows: Record<WindowKey, Trader[]>
  _note?: string
}

export interface RiskConfig {
  bankrollUsd: number
  maxUsdPerPosition: number
  maxOpenPositions: number
  dailyLossKillPct: number
  priceBand: [number, number]
  enginePaused: boolean
}

export type AutopilotRank = 'roi' | 'pnl' | 'pnl_30d' | 'churn'

export interface Autopilot {
  enabled: boolean
  rank: AutopilotRank
  count: number
  minVolume: number
}

/** GET/PATCH /api/settings response: risk config + autopilot. */
export interface Settings extends RiskConfig {
  autopilot: Autopilot
}

/** Patch body for PATCH /api/settings — any subset. */
export interface SettingsPatch {
  bankrollUsd?: number
  maxUsdPerPosition?: number
  maxOpenPositions?: number
  dailyLossKillPct?: number
  priceBandLow?: number
  priceBandHigh?: number
  enginePaused?: boolean
  autopilotEnabled?: boolean
  autopilotRank?: AutopilotRank
  autopilotCount?: number
  autopilotMinVolume?: number
}

export interface TickSummary {
  status: string
  at?: string
  follows?: number
  opened: number
  closed: number
  marked?: number
  errors?: number
  killSwitch?: boolean
  reason?: string
}

export interface BotStatus {
  liveTrading: boolean
  mode: 'PAPER' | 'LIVE'
  walletConfigured: boolean
  engine: {
    intervalSeconds: number
    lastTick: TickSummary | null
    paused: boolean
  }
  risk: RiskConfig
  autopilot: Autopilot
}

export interface Follow {
  wallet: string
  name: string
  allocationUsd: number | null
  active: boolean
  auto: boolean
  createdAt: string
}

export interface BookPosition {
  id: number
  wallet: string
  name: string
  title: string
  outcome: string
  entryPrice: number
  curPrice: number
  shares: number
  stakeUsd: number
  curValue: number
  unrealized: number
  status: 'open' | 'closed'
  openedAt: string
  exitPrice: number | null
  closedAt: string | null
  realizedPnl: number | null
}

export interface Account {
  bankroll: number
  cash: number
  deployed: number
  curValue: number
  realized: number
  unrealized: number
  equity: number
  openCount: number
}

export interface Book {
  account: Account
  open: BookPosition[]
  closed: BookPosition[]
}

export interface EquityPoint {
  t: string | null
  equity: number
  realized: number
}

export interface Performance {
  closedCount: number
  wins: number
  losses: number
  winRate: number | null
  realizedTotal: number
  avgPnl: number
  bestPnl: number
  worstPnl: number
  profitFactor: number | null
  account: Account
  equityCurve: EquityPoint[]
}

export interface ActivityEntry {
  id: number
  ts: string
  kind: 'copy_open' | 'copy_exit' | 'skip' | 'engine'
  wallet: string | null
  name: string | null
  title: string | null
  outcome: string | null
  detail: string
  amount: number | null
}
