/** US book: the same copied bets, priced on Polymarket US. Deliberately simple —
 *  what the bet was, how much was placed, and what it made or lost. This is the
 *  venue you can actually, legally trade, so it's the number that would be real. */
import { useState } from 'react'
import { Page } from '@/components/layout/Page'
import { PageHeader } from '@/components/layout/PageHeader'
import { StatTile } from '@/components/ui/StatTile'
import { EmptyState } from '@/components/ui/EmptyState'
import { Badge } from '@/components/ui/Badge'
import { Value } from '@/components/ui/Value'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useUsBook } from '@/lib/queries'
import { usd, timeAgo, signedUsd2 } from '@/lib/format'
import type { UsBookRow } from '@/lib/types'
import styles from './UsBookPage.module.css'

type Tab = 'open' | 'closed'

export function UsBookPage() {
  const { data: book, isLoading } = useUsBook()
  const [tab, setTab] = useState<Tab>('closed')

  const rows = tab === 'open' ? book?.open ?? [] : book?.closed ?? []

  return (
    <Page>
      <PageHeader
        title="US book"
        subtitle="The same bets, priced on Polymarket US — the venue you could actually trade. What was bet, how much, what it made or lost."
        actions={<Badge tone="paper">SHADOW</Badge>}
      />

      <div className={styles.tiles}>
        <StatTile label="US equity" value={book ? usd(book.equity) : '—'} sub={book ? `${usd(book.bankroll)} start` : undefined} />
        <StatTile
          label="Realized P&L"
          value={book ? <Value value={book.realized}>{signedUsd2(book.realized)}</Value> : '—'}
          sub={book ? `${book.closedCount} closed` : undefined}
        />
        <StatTile
          label="Unrealized P&L"
          value={book ? <Value value={book.unrealized}>{signedUsd2(book.unrealized)}</Value> : '—'}
          sub={book ? `${book.openCount} open` : undefined}
        />
        <StatTile
          label="Net (US)"
          value={book ? <Value value={book.realized + book.unrealized}>{signedUsd2(book.realized + book.unrealized)}</Value> : '—'}
          sub="realized + open"
        />
      </div>

      <div className={styles.toolbar}>
        <SegmentedControl<Tab>
          ariaLabel="Bet status"
          segments={[
            { value: 'closed', label: `Settled${book ? ` · ${book.closedCount}` : ''}` },
            { value: 'open', label: `Open${book ? ` · ${book.openCount}` : ''}` },
          ]}
          value={tab}
          onChange={setTab}
        />
      </div>

      <div className={styles.panel}>
        {isLoading ? (
          <div className={styles.loading}>Loading US book…</div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon="trending"
            title={tab === 'closed' ? 'No settled US bets yet' : 'No open US bets'}
            detail={
              tab === 'closed'
                ? 'Each copied trade that has a Polymarket US match is priced here. Settled bets — with a final gain or loss — appear as those trades close. Only trades opened since the US book went live are tracked.'
                : 'Open copied trades that matched a US market show here, marked to the latest US price.'
            }
          />
        ) : (
          <UsTable rows={rows} tab={tab} />
        )}
      </div>
    </Page>
  )
}

function UsTable({ rows, tab }: { rows: UsBookRow[]; tab: Tab }) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>The bet</th>
          <th className={styles.num}>Placed</th>
          <th className={styles.num}>{tab === 'closed' ? 'Gain / loss' : 'Unrealized'}</th>
          <th className={styles.num}>{tab === 'closed' ? 'Settled' : 'Opened'}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td className={styles.market}>
              <span className={styles.title}>{r.title}</span>
              <span className={styles.outcome}>{r.outcome}</span>
            </td>
            <td className={`${styles.num} tnum`}>{usd(r.stakeUsd)}</td>
            <td className={styles.num}>
              <Value value={r.pnl ?? 0}>{signedUsd2(r.pnl ?? 0)}</Value>
            </td>
            <td className={`${styles.num} ${styles.when}`}>{r.at ? timeAgo(r.at) : '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
