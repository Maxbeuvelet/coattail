/** A single headline figure with a quiet label. Large number commands
 *  attention; supporting text recedes. No card chrome beyond a hairline. */
import type { ReactNode } from 'react'
import styles from './StatTile.module.css'

interface StatTileProps {
  label: string
  value: ReactNode
  /** Small qualifier under the value (e.g. "7 / 10 active"). */
  sub?: ReactNode
  /** Optional right-aligned accessory (sparkline, delta). */
  accessory?: ReactNode
}

export function StatTile({ label, value, sub, accessory }: StatTileProps) {
  return (
    <div className={styles.tile}>
      <div className={styles.head}>
        <span className={styles.label}>{label}</span>
        {accessory && <div className={styles.accessory}>{accessory}</div>}
      </div>
      <div className={`${styles.value} tnum`}>{value}</div>
      {sub && <div className={styles.sub}>{sub}</div>}
    </div>
  )
}
