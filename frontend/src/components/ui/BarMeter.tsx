/** Horizontal magnitude bar for in-table comparison. One neutral-blue hue
 *  (sequential = single hue), thin track, 4px rounded data-end. No gradient. */
import styles from './BarMeter.module.css'

interface BarMeterProps {
  /** 0..1 fraction of the row's max. */
  fraction: number
  /** Trailing label (already formatted). */
  label: string
}

export function BarMeter({ fraction, label }: BarMeterProps) {
  const pct = Math.max(0, Math.min(1, fraction)) * 100
  return (
    <div className={styles.row}>
      <div className={styles.track}>
        <div className={styles.fill} style={{ width: `${pct.toFixed(1)}%` }} />
      </div>
      <span className={`${styles.label} tnum`}>{label}</span>
    </div>
  )
}
