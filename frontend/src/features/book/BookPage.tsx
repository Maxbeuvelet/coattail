/** Book: YOUR positions — simulated in paper mode, real once live. Populated by
 *  the follow engine. Distinct from the traders' books on Discover. */
import { useState } from 'react'
import { Page } from '@/components/layout/Page'
import { PageHeader } from '@/components/layout/PageHeader'
import { StatTile } from '@/components/ui/StatTile'
import { EmptyState } from '@/components/ui/EmptyState'
import { Badge } from '@/components/ui/Badge'
import { Value } from '@/components/ui/Value'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useBook, useStatus } from '@/lib/queries'
import { usd, timeAgo, signedUsd2 } from '@/lib/format'
import type { BookPosition } from '@/lib/types'
import styles from './BookPage.module.css'

type Tab = 'open' | 'closed'

export function BookPage() {
  const { data: status } = useStatus()
  const { data: book, isLoading } = useBook()
  const [tab, setTab] = useState<Tab>('open')

  const acct = book?.account
  const rows = tab === 'open' ? book?.open ?? [] : book?.closed ?? []

  return (
    <Page>
      <PageHeader
        title="Your book"
        subtitle="Positions the bot holds on your behalf, scaled to your sizing."
        actions={
          <Badge tone={status?.mode === 'LIVE' ? 'live' : 'paper'}>{status?.mode ?? '—'}</Badge>
        }
      />

      <div className={styles.tiles}>
        <StatTile label="Equity" value={acct ? usd(acct.equity) : '—'} sub="cash + open value" />
        <StatTile
          label="Unrealized P&L"
          value={
            acct ? (
              <Value value={acct.unrealized}>{signedUsd2(acct.unrealized)}</Value>
            ) : (
              '—'
            )
          }
          sub="mark-to-market"
        />
        <StatTile
          label="Realized P&L"
          value={acct ? <Value value={acct.realized}>{signedUsd2(acct.realized)}</Value> : '—'}
          sub="closed positions"
        />
        <StatTile
          label="Deployed"
          value={acct ? usd(acct.deployed) : '—'}
          sub={acct ? `${acct.openCount} open · ${usd(acct.cash)} cash` : undefined}
        />
      </div>

      <div className={styles.toolbar}>
        <SegmentedControl<Tab>
          ariaLabel="Position status"
          segments={[
            { value: 'open', label: `Open${book ? ` · ${book.open.length}` : ''}` },
            { value: 'closed', label: `Closed${book ? ` · ${book.closed.length}` : ''}` },
          ]}
          value={tab}
          onChange={setTab}
        />
      </div>

      <div className={styles.panel}>
        {isLoading ? (
          <div className={styles.loading}>Loading book…</div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon="wallet"
            title={tab === 'open' ? 'No open positions' : 'Nothing closed yet'}
            detail={
              tab === 'open'
                ? 'When the engine copies a followed trader, the position shows here with live mark-to-market P&L. Follow traders and the first copies appear within a tick.'
                : 'Closed positions land here once a followed trader exits and the engine mirrors the exit.'
            }
          />
        ) : (
          <BookTable rows={rows} tab={tab} />
        )}
      </div>
    </Page>
  )
}

function BookTable({ rows, tab }: { rows: BookPosition[]; tab: Tab }) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>The bet</th>
          <th className={styles.num}>Placed</th>
          <th className={styles.num}>{tab === 'open' ? 'Unrealized' : 'Gain / loss'}</th>
          <th className={styles.num}>{tab === 'open' ? 'Opened' : 'Closed'}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((p) => {
          const pnl = tab === 'open' ? p.unrealized : (p.realizedPnl ?? 0)
          const when = tab === 'open' ? p.openedAt : (p.closedAt ?? p.openedAt)
          return (
            <tr key={p.id}>
              <td className={styles.market}>
                <span className={styles.title}>{p.title}</span>
                <span className={styles.outcome}>{p.outcome}</span>
              </td>
              <td className={`${styles.num} tnum`}>{usd(p.stakeUsd)}</td>
              <td className={styles.num}>
                <Value value={pnl}>{signedUsd2(pnl)}</Value>
              </td>
              <td className={`${styles.num} ${styles.when}`}>{timeAgo(when)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
