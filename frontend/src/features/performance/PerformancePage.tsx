/** Performance: one question — is this making money or losing it?
 *
 *  Deliberately spare. The page used to carry two US-shadow panels side by
 *  side, one of which was a known-broken matcher kept only for comparison, and
 *  reading it required knowing which of six numbers mattered. Everything that
 *  does not change a decision has been removed. */
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

  const acct = perf?.account
  const net = acct ? acct.equity - acct.bankroll : 0
  const hasClosed = (perf?.closedCount ?? 0) > 0
  const gap = perf?.whaleGap
  const us = perf?.usShadowV2
  const live = status?.mode?.startsWith('LIVE')

  return (
    <Page>
      <PageHeader
        title="Performance"
        subtitle="Closed trades only. Open positions can bounce; closed ones are real."
        actions={<Badge tone={status?.mode === 'LIVE' ? 'live' : 'paper'}>{status?.mode ?? '—'}</Badge>}
      />

      {isLoading ? (
        <div className={styles.loading}>Loading…</div>
      ) : !hasClosed ? (
        <EmptyState
          icon="trending"
          title="Nothing has closed yet"
          detail="Numbers appear as positions resolve or the copied trader exits. With same-day sports that is usually hours, not days."
        />
      ) : (
        <>
          {/* The headline: up or down, in dollars, before anything else. */}
          <div className={styles.headline}>
            <span className={styles.headlineLabel}>
              {net >= 0 ? 'Up' : 'Down'} on {perf!.closedCount} closed trades
            </span>
            <Value value={net} className={styles.headlineValue}>{signedUsd2(net)}</Value>
            <span className={styles.headlineSub}>
              {usd(acct!.bankroll)} start → {usd(acct!.equity)} now
            </span>
          </div>

          <div className={styles.tiles}>
            <StatTile
              label="Win rate"
              value={perf!.winRate != null ? ratioPct(perf!.winRate) : '—'}
              sub={`${perf!.wins} won · ${perf!.losses} lost`}
            />
            <StatTile
              label="Average trade"
              value={<Value value={perf!.avgPnl}>{signedUsd2(perf!.avgPnl)}</Value>}
              sub="per closed trade"
            />
            <StatTile
              label="Best / worst"
              value={`${signedUsd2(perf!.bestPnl)} / ${signedUsd2(perf!.worstPnl)}`}
              sub="single trades"
            />
            <StatTile
              label="Still open"
              value={acct!.openCount}
              sub={<Value value={acct!.unrealized}>{signedUsd2(acct!.unrealized)} unrealized</Value>}
            />
          </div>

          <div className={styles.panel}>
            <EquityCurve points={perf!.equityCurve} baseline={acct!.bankroll} />
          </div>

          {/* The measured drag: we buy at the trader's CURRENT price, which is
              usually worse than the price they got. */}
          {gap && gap.trades > 0 && (
            <div className={styles.callout}>
              <strong>You buy after the trader does.</strong> Across {gap.trades} copied trades you paid
              on average <strong>{gap.avgGap >= 0 ? '+' : ''}{gap.avgGap.toFixed(3)}</strong> versus
              what they paid
              {gap.avgPct ? <> ({gap.avgPct >= 0 ? '+' : ''}{Math.round(gap.avgPct * 100)}%)</> : null}
              {gap.worseRate != null && <> — worse on {ratioPct(gap.worseRate)} of them</>}.
              By the time a position shows up in their public feed, the price has already moved to
              reflect it.
            </div>
          )}

          {/* Only shown on the paper bot, where it answers a real question:
              would these same picks survive on the venue you can actually use? */}
          {!live && us && us.closedCount > 0 && (
            <div className={styles.panel}>
              <div className={styles.panelHead}>
                <h2 className={styles.panelTitle}>If these trades ran on Polymarket US</h2>
                <span className={styles.panelHint}>{us.closedCount} matched · the venue you can actually trade</span>
              </div>
              <div className={styles.compare}>
                <div className={styles.compareItem}>
                  <span className={styles.compareLabel}>Here (simulated)</span>
                  <Value value={us.ownRealizedMatched} className={styles.compareValue}>
                    {signedUsd2(us.ownRealizedMatched)}
                  </Value>
                </div>
                <div className={styles.compareItem}>
                  <span className={styles.compareLabel}>On Polymarket US</span>
                  <Value value={us.realizedTotal} className={styles.compareValue}>
                    {signedUsd2(us.realizedTotal)}
                  </Value>
                </div>
                <div className={styles.compareItem}>
                  <span className={styles.compareLabel}>Copyable at all</span>
                  <span className={styles.compareValue}>
                    {us.matchRate != null ? ratioPct(us.matchRate) : '—'}
                  </span>
                </div>
              </div>
            </div>
          )}

          <p className={styles.caveat}>
            {perf!.closedCount < 100
              ? <>Only {perf!.closedCount} closed trades — too few to tell skill from luck. Treat anything under ~100 as noise.</>
              : <>Based on {perf!.closedCount} closed trades.</>}
            {' '}Simulated results fill instantly at the trader&apos;s price with no fees; real trading
            pays a spread on entry and exit plus taker fees each way.
          </p>
        </>
      )}
    </Page>
  )
}
