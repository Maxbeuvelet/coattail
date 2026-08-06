/** Real money. Every number here is read from Polymarket US itself, not from
 *  Coattail's own book — the two can disagree, and when they do the exchange is
 *  right. That is not hypothetical: the first live run filled nine orders that
 *  the local book never recorded. */
import { Page } from '@/components/layout/Page'
import { PageHeader } from '@/components/layout/PageHeader'
import { StatTile } from '@/components/ui/StatTile'
import { EmptyState } from '@/components/ui/EmptyState'
import { Badge } from '@/components/ui/Badge'
import { Value } from '@/components/ui/Value'
import { useLiveBook, useStatus } from '@/lib/queries'
import { usd, signedUsd2 } from '@/lib/format'
import styles from './LiveBookPage.module.css'

export function LiveBookPage() {
  const { data: status } = useStatus()
  const { data, isLoading } = useLiveBook()

  const live = status?.mode ?? '—'
  const rows = data?.positions ?? []

  return (
    <Page>
      <PageHeader
        title="Live book"
        subtitle="Real positions on Polymarket US, read from the exchange."
        actions={<Badge tone={live === 'LIVE' ? 'live' : 'paper'}>{live}</Badge>}
      />

      {isLoading ? (
        <div className={styles.loading}>Loading…</div>
      ) : !data?.connected ? (
        <EmptyState
          icon="wallet"
          title="Not connected to Polymarket US"
          detail={data?.reason ?? 'Set POLYMARKET_KEY_ID and POLYMARKET_SECRET_KEY in the backend .env.'}
        />
      ) : (
        <>
          <div className={styles.tiles}>
            <StatTile label="Cash" value={usd(data.cash)} sub="available to trade" />
            <StatTile label="Invested" value={usd(data.invested)} sub={`${data.positionCount} positions`} />
            <StatTile
              label="Market value"
              value={usd(data.marketValue)}
              sub={<Value value={data.unrealized}>{signedUsd2(data.unrealized)} unrealized</Value>}
            />
            <StatTile label="If all win" value={usd(data.ifAllWin)} sub="max payout at resolution" />
          </div>

          <p className={styles.hint}>
            <strong>Marked at the bid</strong> — what you could actually sell into right now, not
            the midpoint. Unrealized will read negative on a fresh position simply because you
            crossed the spread to get in; it is not a loss unless the market resolves against you.
            The column that decides the outcome is <strong>If wins</strong>.
          </p>

          {rows.length === 0 ? (
            <EmptyState
              icon="wallet"
              title="No open positions"
              detail="Nothing is currently held on Polymarket US. Positions appear here the moment an order fills, whether or not Coattail recorded it."
            />
          ) : (
            <div className={styles.panel}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th className={styles.market}>Market</th>
                    <th className={styles.num}>Contracts</th>
                    <th className={styles.num}>Avg cost</th>
                    <th className={styles.num}>Mark</th>
                    <th className={styles.num}>Paid</th>
                    <th className={styles.num}>Value</th>
                    <th className={styles.num}>Unrealized</th>
                    <th className={styles.num}>If wins</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((p) => (
                    <tr key={p.slug}>
                      <td className={styles.market}>
                        <span className={styles.title} title={p.title}>{p.title}</span>
                        <span className={styles.outcome}>{p.outcome}</span>
                        {p.expired && <span className={styles.settled}>settled</span>}
                      </td>
                      <td className={styles.num}>{p.contracts}</td>
                      <td className={styles.num}>{p.avgPrice?.toFixed(3) ?? '—'}</td>
                      <td className={styles.num}>{p.mark?.toFixed(3) ?? '—'}</td>
                      <td className={styles.num}>{usd(p.cost)}</td>
                      <td className={styles.num}>{p.value != null ? usd(p.value) : '—'}</td>
                      <td className={styles.num}>
                        {p.unrealized != null ? (
                          <Value value={p.unrealized}>{signedUsd2(p.unrealized)}</Value>
                        ) : '—'}
                      </td>
                      <td className={`${styles.num} ${styles.ifWins}`}>{usd(p.ifWins)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Page>
  )
}
