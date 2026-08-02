/** One US-shadow panel: head-to-head numbers on the matched trades + its equity
 *  curve. Rendered twice on the Performance page — once for the original
 *  event-only matcher, once for the market-aware one — so the two can be read
 *  against each other on the same trades. */
import { EmptyState } from '@/components/ui/EmptyState'
import { Value } from '@/components/ui/Value'
import type { UsShadow } from '@/lib/types'
import { signedUsd2, ratioPct } from '@/lib/format'
import { EquityCurve } from './EquityCurve'
import styles from './PerformancePage.module.css'

interface UsShadowPanelProps {
  shadow: UsShadow
  bankroll: number
  title: string
  hint: string
  /** Curve + dot color, so the two series read as distinct. */
  accent: string
  /** Optional callout above the numbers (e.g. flagging the broken matcher). */
  note?: React.ReactNode
  /** Shown when nothing has closed yet. */
  emptyDetail: string
  className?: string
}

export function UsShadowPanel({
  shadow,
  bankroll,
  title,
  hint,
  accent,
  note,
  emptyDetail,
  className,
}: UsShadowPanelProps) {
  return (
    <div className={`${styles.panel} ${styles.usPanel} ${className ?? ''}`} style={{ borderLeftColor: accent }}>
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle}>
          <span className={styles.compareDot} style={{ background: accent }} />
          {title}
        </h2>
        <span className={styles.panelHint}>{hint}</span>
      </div>

      {note && <p className={styles.note}>{note}</p>}

      {shadow.closedCount > 0 ? (
        <>
          <div className={styles.compare}>
            <div className={styles.compareItem}>
              <span className={styles.compareLabel}>Coattail (international)</span>
              <Value value={shadow.ownRealizedMatched} className={styles.compareValue}>
                {signedUsd2(shadow.ownRealizedMatched)}
              </Value>
            </div>
            <div className={styles.compareItem}>
              <span className={styles.compareLabel}>Polymarket US</span>
              <Value value={shadow.realizedTotal} className={styles.compareValue}>
                {signedUsd2(shadow.realizedTotal)}
              </Value>
            </div>
            <div className={styles.compareItem}>
              <span className={styles.compareLabel}>Venue gap</span>
              <Value value={shadow.realizedTotal - shadow.ownRealizedMatched} className={styles.compareValue}>
                {signedUsd2(shadow.realizedTotal - shadow.ownRealizedMatched)}
              </Value>
            </div>
            <div className={styles.compareItem}>
              <span className={styles.compareLabel}>Closed</span>
              <span className={styles.compareValue}>{shadow.closedCount}</span>
            </div>
            <div className={styles.compareItem}>
              <span className={styles.compareLabel}>Win rate</span>
              <span className={styles.compareValue}>
                {shadow.winRate != null ? ratioPct(shadow.winRate) : '—'}
              </span>
            </div>
            <div className={styles.compareItem}>
              <span className={styles.compareLabel}>Matched on US</span>
              <span className={styles.compareValue}>
                {shadow.matched}/{shadow.totalTrades}
                {shadow.matchRate != null ? ` · ${ratioPct(shadow.matchRate)}` : ''}
              </span>
            </div>
          </div>
          <EquityCurve points={shadow.equityCurve} baseline={bankroll} accent={accent} />
        </>
      ) : (
        <EmptyState icon="trending" title="Building the US comparison" detail={emptyDetail} />
      )}
    </div>
  )
}
