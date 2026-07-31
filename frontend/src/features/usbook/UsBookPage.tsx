/** US book: the same copied bets, priced on Polymarket US. Deliberately simple —
 *  what the bet was, how much was placed, and what it made or lost.
 *
 *  The gap filter is the key tool: restrict to trades where US priced the bet
 *  close to the whale's price, to see whether that *subset* is profitable — i.e.
 *  whether the venue-price gap is dodgeable (filter to close-priced bets) or
 *  fatal (even they lose). All read-only; it changes nothing the engine does. */
import { useMemo, useState } from 'react'
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
type GapFilter = 'all' | '10' | '5' | '3'

const GAP_LABEL: Record<GapFilter, string> = { all: 'All bets', '10': '≤10¢', '5': '≤5¢', '3': '≤3¢' }

/** e.g. +2¢ / −26¢ */
function gapText(gap: number): string {
  const c = Math.round(gap * 100)
  return `${c > 0 ? '+' : c < 0 ? '−' : ''}${Math.abs(c)}¢`
}

export function UsBookPage() {
  const { data: book, isLoading } = useUsBook()
  const [tab, setTab] = useState<Tab>('closed')
  const [gap, setGap] = useState<GapFilter>('all')

  const thresholdC = gap === 'all' ? null : Number(gap)
  const withinGap = (r: UsBookRow) => thresholdC == null || Math.abs(r.gap) * 100 <= thresholdC + 1e-9

  const openF = useMemo(() => (book?.open ?? []).filter(withinGap), [book, thresholdC])
  const closedF = useMemo(() => (book?.closed ?? []).filter(withinGap), [book, thresholdC])

  const realized = closedF.reduce((s, r) => s + (r.pnl ?? 0), 0)
  const unrealized = openF.reduce((s, r) => s + (r.pnl ?? 0), 0)
  const bankroll = book?.bankroll ?? 0
  const rows = tab === 'open' ? openF : closedF

  return (
    <Page>
      <PageHeader
        title="US book"
        subtitle="The same bets, priced on Polymarket US. Filter to close-priced bets to see if the venue gap is dodgeable or fatal."
        actions={<Badge tone="paper">SHADOW</Badge>}
      />

      <div className={styles.tiles}>
        <StatTile label="US equity" value={usd(bankroll + realized + unrealized)} sub={`${usd(bankroll)} start`} />
        <StatTile
          label="Realized P&L"
          value={<Value value={realized}>{signedUsd2(realized)}</Value>}
          sub={`${closedF.length} closed`}
        />
        <StatTile
          label="Unrealized P&L"
          value={<Value value={unrealized}>{signedUsd2(unrealized)}</Value>}
          sub={`${openF.length} open`}
        />
        <StatTile
          label="Net (US)"
          value={<Value value={realized + unrealized}>{signedUsd2(realized + unrealized)}</Value>}
          sub={gap === 'all' ? 'all matched bets' : `US within ${gap}¢ only`}
        />
      </div>

      <div className={styles.toolbar}>
        <SegmentedControl<Tab>
          ariaLabel="Bet status"
          segments={[
            { value: 'closed', label: `Settled${book ? ` · ${closedF.length}` : ''}` },
            { value: 'open', label: `Open${book ? ` · ${openF.length}` : ''}` },
          ]}
          value={tab}
          onChange={setTab}
        />
        <SegmentedControl<GapFilter>
          ariaLabel="Price-gap filter"
          segments={(['all', '10', '5', '3'] as GapFilter[]).map((g) => ({ value: g, label: GAP_LABEL[g] }))}
          value={gap}
          onChange={setGap}
        />
      </div>

      <p className={styles.hint}>
        <strong>Gap</strong> = how far US priced the bet from the whale&apos;s entry. Small gap = riding the
        whale onto US actually works; big gap = you&apos;re taking a different price than the edge was built on.
        Filter down and watch whether the close-priced bets stay green.
      </p>

      <div className={styles.panel}>
        {isLoading ? (
          <div className={styles.loading}>Loading US book…</div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon="trending"
            title={gap === 'all' ? (tab === 'closed' ? 'No settled US bets yet' : 'No open US bets') : 'None within that gap'}
            detail={
              gap === 'all'
                ? 'Each copied trade with a Polymarket US match is priced here. Settled bets — with a final gain or loss — appear as those trades close. Only trades opened since the US book went live are tracked.'
                : `No ${tab} bets where US priced within ${gap}¢ of the whale. Loosen the filter to see more.`
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
          <th className={styles.num}>US gap</th>
          <th className={styles.num}>{tab === 'closed' ? 'Gain / loss' : 'Unrealized'}</th>
          <th className={styles.num}>{tab === 'closed' ? 'Settled' : 'Opened'}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const big = Math.abs(r.gap) * 100 >= 8
          return (
            <tr key={r.id}>
              <td className={styles.market}>
                <span className={styles.title}>{r.title}</span>
                <span className={styles.outcome}>{r.outcome}</span>
              </td>
              <td className={`${styles.num} tnum`}>{usd(r.stakeUsd)}</td>
              <td className={`${styles.num} tnum ${big ? styles.gapBig : styles.gapSmall}`}>{gapText(r.gap)}</td>
              <td className={styles.num}>
                <Value value={r.pnl ?? 0}>{signedUsd2(r.pnl ?? 0)}</Value>
              </td>
              <td className={`${styles.num} ${styles.when}`}>{r.at ? timeAgo(r.at) : '—'}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
