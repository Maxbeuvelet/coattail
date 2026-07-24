/** Number / money / price formatting. Consistent everywhere the data shows. */

const usdFull = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

/** Full dollars, no cents: $1,234,567 */
export function usd(n: number): string {
  return usdFull.format(n)
}

const usd2Fmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** Dollars with cents, for small P&L where whole-dollar rounding lies: $1.85 */
export function usd2(n: number): string {
  return usd2Fmt.format(n)
}

/** Signed dollars-and-cents for P&L: +$1.85, −$0.40 */
export function signedUsd2(n: number): string {
  return `${n >= 0 ? '+' : '−'}${usd2(Math.abs(n))}`
}

/** Compact money for dense cells / axes: $22.1M, $311K, $842 */
export function usdCompact(n: number): string {
  const a = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (a >= 1_000_000) return `${sign}$${(a / 1_000_000).toFixed(1)}M`
  if (a >= 1_000) return `${sign}$${(a / 1_000).toFixed(a >= 100_000 ? 0 : 1)}K`
  return `${sign}$${a.toFixed(0)}`
}

/** Signed percent for P&L: +23.5%, -16.9% */
export function pctSigned(n: number, dp = 1): string {
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(dp)}%`
}

/** Ratio (0.51) → 51% for ROI-style values. */
export function ratioPct(n: number, dp = 0): string {
  return `${(n * 100).toFixed(dp)}%`
}

/** Market price as cents: 0.9532 → 95¢ */
export function cents(p: number): string {
  return `${Math.round(p * 100)}¢`
}

/** 0x1234…abcd */
export function shortAddr(wallet: string): string {
  if (wallet.length <= 12) return wallet
  return `${wallet.slice(0, 6)}…${wallet.slice(-4)}`
}

/** Relative "3m ago" style, coarse. */
export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const secs = Math.round((Date.now() - then) / 1000)
  if (secs < 60) return `${secs}s ago`
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

export type Sign = 'pos' | 'neg' | 'zero'
export function signOf(n: number): Sign {
  if (n > 0) return 'pos'
  if (n < 0) return 'neg'
  return 'zero'
}
