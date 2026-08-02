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
import { UsShadowPanel } from './UsShadowPanel'
import styles from './PerformancePage.module.css'

export function PerformancePage() {
  const { data: status } = useStatus()
  const { data: perf, isLoading } = usePerformance()

  const hasClosed = (perf?.closedCount ?? 0) > 0
  const acct = perf?.account
  const us = perf?.usShadow
  const usV2 = perf?.usShadowV2

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
            cross-venue price gap — not the picks — is where the edge dies.
            Two matchers run side by side; see us_pricing.py for why. ── */}
      {perf && us && (
        <UsShadowPanel
          shadow={us}
          bankroll={perf.account.bankroll}
          accent="var(--info)"
          title="If executed on Polymarket US — legacy matcher"
          hint="event-only match · superseded"
          note={
            <>
              <strong>Do not trade on this curve.</strong> This matcher only matched the{' '}
              <em>event</em>, then priced the first market in it — so a bet on “both teams to
              score” could be priced off “team A wins”. It also read{' '}
              <code>outcomePrices</code> as one price per outcome when it is really{' '}
              <code>[bestBid, bestAsk]</code>. Kept running only as the baseline for the
              corrected curve below.
            </>
          }
          emptyDetail={
            us.matched > 0
              ? `${us.matched} trade${us.matched === 1 ? '' : 's'} matched so far — waiting for ${us.matched === 1 ? 'it' : 'them'} to close.`
              : 'This is the original comparison curve. It fills in as matched trades close.'
          }
        />
      )}

      {/* ── The corrected shadow: matches the market, not just the game, and
            prices Yes at the ask / No at 1−bid. This is the one to judge. ── */}
      {perf && usV2 && (
        <UsShadowPanel
          shadow={usV2}
          bankroll={perf.account.bankroll}
          accent="var(--warn)"
          title="If executed on Polymarket US — market-matched"
          hint="same market, same outcome, real bid/ask + est. fee"
          className={styles.v2Panel}
          note={
            <>
              Matches the exact market <em>and</em> outcome, prices Yes at the ask and No at
              1−bid, and refuses to guess — unmatched or ambiguous trades are skipped rather
              than mispriced. Expect a lower match rate than the curve above, and treat that
              as the honest one. Starts from the trades opened after this shipped.
            </>
          }
          emptyDetail={
            usV2.matched > 0
              ? `${usV2.matched} trade${usV2.matched === 1 ? '' : 's'} matched with a confirmed market and a locked-in US price — waiting for ${usV2.matched === 1 ? 'it' : 'them'} to close. This curve and the head-to-head appear as they resolve.`
              : 'Every new copied trade is priced against the exact matching Polymarket US market. This curve fills in as those trades close — then compare it against the legacy curve above to see how much of the old number was matching error.'
          }
        />
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
