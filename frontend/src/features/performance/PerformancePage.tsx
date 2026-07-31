/** Performance: the "is it working?" view. Realized-trade stats + equity curve.
 *  Everything here is about CLOSED trades — open marks bounce, closes are real. */
import { Page } from '@/components/layout/Page'
import { PageHeader } from '@/components/layout/PageHeader'
import { StatTile } from '@/components/ui/StatTile'
import { EmptyState } from '@/components/ui/EmptyState'
import { Badge } from '@/components/ui/Badge'
import { Value } from '@/components/ui/Value'
import { usePerformance, useStatus } from '@/lib/queries'
import { usd, signedUsd2, ratioPct } from '@/lib/format'
import { EquityCurve } from './EquityCurve'
import styles from './PerformancePage.module.css'

export function PerformancePage() {
  const { data: status } = useStatus()
  const { data: perf, isLoading } = usePerformance()

  const hasClosed = (perf?.closedCount ?? 0) > 0
  const acct = perf?.account
  const us = perf?.usShadow

  return (
    <Page>
      <PageHeader
        title="Performance"
        subtitle="How the strategy is doing on realized (closed) trades — the honest scoreboard."
        actions={<Badge tone={status?.mode === 'LIVE' ? 'live' : 'paper'}>{status?.mode ?? '—'}</Badge>}
      />

      <div className={styles.tiles}>
        <StatTile
          label="Equity"
          value={acct ? usd(acct.equity) : '—'}
          sub={acct ? <Value value={acct.equity - acct.bankroll}>{signedUsd2(acct.equity - acct.bankroll)} vs start</Value> : undefined}
        />
        <StatTile
          label="Realized P&L"
          value={perf ? <Value value={perf.realizedTotal}>{signedUsd2(perf.realizedTotal)}</Value> : '—'}
          sub="closed trades"
        />
        <StatTile
          label="Win rate"
          value={perf?.winRate != null ? ratioPct(perf.winRate) : '—'}
          sub={perf ? `${perf.wins}W · ${perf.losses}L` : undefined}
        />
        <StatTile label="Closed trades" value={perf?.closedCount ?? '—'} sub="sample size" />
        <StatTile
          label="Avg / trade"
          value={perf ? <Value value={perf.avgPnl}>{signedUsd2(perf.avgPnl)}</Value> : '—'}
          sub="realized"
        />
        <StatTile
          label="Profit factor"
          value={perf?.profitFactor != null ? perf.profitFactor.toFixed(2) : '—'}
          sub="gross win / loss"
        />
      </div>

      <div className={styles.panel}>
        <div className={styles.panelHead}>
          <h2 className={styles.panelTitle}>Equity curve</h2>
          <span className={styles.panelHint}>realized equity per closed trade</span>
        </div>
        {isLoading ? (
          <div className={styles.loading}>Loading…</div>
        ) : hasClosed && perf ? (
          <EquityCurve points={perf.equityCurve} baseline={perf.account.bankroll} />
        ) : (
          <EmptyState
            icon="trending"
            title="No closed trades yet"
            detail="The curve and win rate appear as positions close — either a followed trader exits or a market resolves. With the sports-heavy books these traders hold, that usually starts within a day or two."
          />
        )}
      </div>

      {/* ── US shadow: the same trades priced on Polymarket US (the venue you can
            actually, legally trade). If this curve trails the one above, the
            cross-venue price gap — not the picks — is where the edge dies. ── */}
      {perf && (
        <div className={`${styles.panel} ${styles.usPanel}`}>
          <div className={styles.panelHead}>
            <h2 className={styles.panelTitle}>
              <span className={styles.compareDot} style={{ background: 'var(--info)' }} />
              If executed on Polymarket US
            </h2>
            <span className={styles.panelHint}>same trades, real US prices + est. fee — the honest cross-venue test</span>
          </div>
          {us && us.closedCount > 0 ? (
            <>
              <div className={styles.compare}>
                <div className={styles.compareItem}>
                  <span className={styles.compareLabel}>Coattail (international)</span>
                  <Value value={us.ownRealizedMatched} className={styles.compareValue}>
                    {signedUsd2(us.ownRealizedMatched)}
                  </Value>
                </div>
                <div className={styles.compareItem}>
                  <span className={styles.compareLabel}>Polymarket US</span>
                  <Value value={us.realizedTotal} className={styles.compareValue}>
                    {signedUsd2(us.realizedTotal)}
                  </Value>
                </div>
                <div className={styles.compareItem}>
                  <span className={styles.compareLabel}>Venue gap</span>
                  <Value value={us.realizedTotal - us.ownRealizedMatched} className={styles.compareValue}>
                    {signedUsd2(us.realizedTotal - us.ownRealizedMatched)}
                  </Value>
                </div>
                <div className={styles.compareItem}>
                  <span className={styles.compareLabel}>Matched on US</span>
                  <span className={styles.compareValue}>
                    {us.matched}/{us.totalTrades}
                    {us.matchRate != null ? ` · ${ratioPct(us.matchRate)}` : ''}
                  </span>
                </div>
              </div>
              <EquityCurve points={us.equityCurve} baseline={perf.account.bankroll} accent="var(--info)" />
            </>
          ) : (
            <EmptyState
              icon="trending"
              title="Building the US comparison"
              detail="Every copied trade is also priced on Polymarket US as it opens and closes. This curve fills in as those matched trades close — then you can see, side by side, whether the same picks make money at the prices you could actually get."
            />
          )}
        </div>
      )}

      {hasClosed && perf && (
        <p className={styles.caveat}>
          <strong>Read this honestly.</strong> {perf.closedCount} closed trade
          {perf.closedCount === 1 ? '' : 's'} so far — treat anything under ~100 as noise, not signal.
          And remember copies fill at the trader&apos;s <em>current</em> price, not their entry, so a
          great trader can still net you roughly break-even after that slippage. This page exists to
          measure exactly that.
        </p>
      )}
    </Page>
  )
}
