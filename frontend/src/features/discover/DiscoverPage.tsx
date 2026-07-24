/** Discover: the leaderboard of top traders + their open books. The primary
 *  scan surface — pick who's worth copying, then follow them. */
import { useMemo, useState } from 'react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Page } from '@/components/layout/Page'
import { StatTile } from '@/components/ui/StatTile'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { Value } from '@/components/ui/Value'
import { EmptyState } from '@/components/ui/EmptyState'
import { useSnapshot } from '@/lib/queries'
import { useFollows } from '@/lib/useFollows'
import { usdCompact, timeAgo } from '@/lib/format'
import type { Trader, WindowKey } from '@/lib/types'
import { LeaderboardTable, type SortKey } from './LeaderboardTable'
import styles from './DiscoverPage.module.css'

const WINDOW_SEGMENTS = [
  { value: 'all_time' as WindowKey, label: 'All-time' },
  { value: 'last_30d' as WindowKey, label: 'Last 30 days' },
]

const SORT_SEGMENTS = [
  { value: 'pnl' as SortKey, label: 'Profit' },
  { value: 'roi' as SortKey, label: 'ROI' },
  { value: 'volume' as SortKey, label: 'Volume' },
]

export function DiscoverPage() {
  const { data, isLoading, isError, error, dataUpdatedAt } = useSnapshot(10)
  const { count } = useFollows()
  const [win, setWin] = useState<WindowKey>('all_time')
  const [sort, setSort] = useState<SortKey>('pnl')

  const rows: Trader[] = useMemo(() => data?.windows[win] ?? [], [data, win])

  const stats = useMemo(() => {
    const withOpen = rows.filter((r) => r.positions.length > 0).length
    const totalPnl = rows.reduce((s, r) => s + r.pnl, 0)
    const totalExp = rows.reduce((s, r) => s + r.openExposure, 0)
    return { withOpen, totalPnl, totalExp }
  }, [rows])

  return (
    <Page>
      <PageHeader
        title="Discover"
        subtitle={
          <>
            Top traders ranked by performance, with live open positions.{' '}
            {data && (
              <span className={styles.freshness}>
                Updated {timeAgo(new Date(dataUpdatedAt).toISOString())}
                {data._note ? ' · sample data' : ''}
              </span>
            )}
          </>
        }
        actions={
          <div className={styles.controls}>
            <SegmentedControl
              ariaLabel="Time window"
              segments={WINDOW_SEGMENTS}
              value={win}
              onChange={setWin}
            />
            <SegmentedControl
              ariaLabel="Sort traders by"
              segments={SORT_SEGMENTS}
              value={sort}
              onChange={setSort}
            />
          </div>
        }
      />

      {isError ? (
        <EmptyState
          icon="alert"
          title="Couldn't load the leaderboard"
          detail={
            <>
              The backend didn't respond. Make sure it's running on port 8000.
              <br />
              <code className={styles.err}>{(error as Error)?.message}</code>
            </>
          }
        />
      ) : (
        <>
          <div className={styles.tiles}>
            <StatTile label="Traders tracked" value={isLoading ? '—' : rows.length} />
            <StatTile
              label="Combined profit"
              value={
                isLoading ? (
                  '—'
                ) : (
                  <Value value={stats.totalPnl} tone="pos">
                    {usdCompact(stats.totalPnl)}
                  </Value>
                )
              }
            />
            <StatTile
              label="With open positions"
              value={isLoading ? '—' : stats.withOpen}
              sub={isLoading ? undefined : `of ${rows.length} traders`}
            />
            <StatTile
              label="Open exposure"
              value={isLoading ? '—' : usdCompact(stats.totalExp)}
              sub="across tracked books"
            />
            <StatTile label="Following" value={count} sub="you copy" />
          </div>

          <LeaderboardTable rows={rows} sort={sort} loading={isLoading} />
        </>
      )}
    </Page>
  )
}
