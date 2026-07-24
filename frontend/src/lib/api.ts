/** Thin typed fetch wrapper. Same-origin relative paths; Vite proxies /api. */
import type {
  ActivityEntry,
  BotStatus,
  Book,
  Follow,
  LeaderWindow,
  OrderBy,
  Performance,
  Position,
  Settings,
  SettingsPatch,
  Snapshot,
  TickSummary,
  Trader,
} from './types'

class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// ── Owner key (unlocks control on a public/shared deployment) ──────────────
const OWNER_KEY_STORAGE = 'copybot.ownerKey'

export function getOwnerKey(): string | null {
  try {
    return localStorage.getItem(OWNER_KEY_STORAGE)
  } catch {
    return null
  }
}

export function setOwnerKey(key: string | null): void {
  try {
    if (key) localStorage.setItem(OWNER_KEY_STORAGE, key)
    else localStorage.removeItem(OWNER_KEY_STORAGE)
  } catch {
    /* storage disabled */
  }
}

function authHeaders(): Record<string, string> {
  const k = getOwnerKey()
  return k ? { 'X-Owner-Key': k } : {}
}

async function get<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(path, window.location.origin)
  if (params) {
    for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v))
  }
  const res = await fetch(url.pathname + url.search, {
    headers: { Accept: 'application/json', ...authHeaders() },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body?.detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json())?.detail ?? detail
    } catch {
      /* non-JSON */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  whoami: () => get<{ authRequired: boolean; owner: boolean }>('/api/whoami'),
  status: () => get<BotStatus>('/api/status'),
  snapshot: (top = 10) => get<Snapshot>('/api/snapshot', { top }),
  leaderboard: (window: LeaderWindow, top: number, orderBy: OrderBy) =>
    get<Trader[]>('/api/leaderboard', { window, top, orderBy }),
  positions: (wallet: string, limit = 6) =>
    get<Position[]>(`/api/positions/${wallet}`, { limit }),

  // ── copy-trade surface ──
  follows: () => get<Follow[]>('/api/follows'),
  addFollow: (wallet: string, name: string, allocationUsd?: number | null) =>
    send<Follow>('POST', '/api/follows', { wallet, name, allocationUsd }),
  removeFollow: (wallet: string) => send<void>('DELETE', `/api/follows/${wallet}`),
  setAllocation: (wallet: string, allocationUsd: number | null) =>
    send<Follow>('PATCH', `/api/follows/${wallet}`, { allocationUsd }),

  book: () => get<Book>('/api/book'),
  performance: () => get<Performance>('/api/performance'),
  activity: (limit = 100) => get<ActivityEntry[]>('/api/activity', { limit }),
  tickNow: () => send<TickSummary>('POST', '/api/engine/tick'),

  settings: () => get<Settings>('/api/settings'),
  updateSettings: (patch: SettingsPatch) => send<Settings>('PATCH', '/api/settings', patch),
  resetBook: () => send<{ ok: boolean }>('POST', '/api/engine/reset'),
}

export { ApiError }
