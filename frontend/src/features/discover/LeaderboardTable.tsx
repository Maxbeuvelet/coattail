/** The leaderboard proper. A real table (dense, sortable, keyboard-navigable);
 *  each trader expands to reveal their open book. */
import { useMemo, useState } from 'react'
import type { Trader } from '@/lib/types'
import { TraderRow } from './TraderRow'
import styles from './LeaderboardTable.module.css'

export type SortKey = 'pnl' | 'roi' | 'volume'

interface LeaderboardTableProps {
  rows: Trader[]
  sort: SortKey
  loading?: boolean
}

export function LeaderboardTable({ rows, sort, loading }: LeaderboardTableProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const sorted = useMemo(() => {
    const copy = [...rows]
    copy.sort((a, b) => b[sort] - a[sort])
    return copy
  }, [rows, sort])

  // Magnitude scale for the in-cell profit bar (relative to the leader).
  const maxPnl = useMemo(() => Math.max(1, ...rows.map((r) => r.pnl)), [rows])

  const toggle = (wallet: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(wallet)) next.delete(wallet)
      else next.add(wallet)
      return next
    })

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.skeleton} aria-busy="true" aria-label="Loading leaderboard">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className={styles.skelRow} />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.colRank} scope="col">
              #
            </th>
            <th className={styles.colTrader} scope="col">
              Trader
            </th>
            <th className={`${styles.colNum} ${sort === 'pnl' ? styles.sorted : ''}`} scope="col">
              Profit
            </th>
            <th className={`${styles.colNum} ${sort === 'roi' ? styles.sorted : ''}`} scope="col">
              ROI
            </th>
            <th
              className={`${styles.colNum} ${styles.hideSm} ${sort === 'volume' ? styles.sorted : ''}`}
              scope="col"
            >
              Volume
            </th>
            <th className={`${styles.colNum} ${styles.hideSm}`} scope="col">
              Open exp.
            </th>
            <th className={styles.colFollow} scope="col">
              <span className={styles.srOnly}>Follow</span>
            </th>
            <th className={styles.colChev} scope="col" aria-hidden="true" />
          </tr>
        </thead>
        {sorted.map((trader) => (
          <TraderRow
            key={trader.wallet}
            trader={trader}
            maxPnl={maxPnl}
            expanded={expanded.has(trader.wallet)}
            onToggle={() => toggle(trader.wallet)}
          />
        ))}
      </table>
    </div>
  )
}
