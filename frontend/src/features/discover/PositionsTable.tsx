/** A trader's open book, shown when their row is expanded. Compact, with the
 *  entry→current price move and unrealized P&L per position. */
import type { Position } from '@/lib/types'
import { Value } from '@/components/ui/Value'
import { usd, cents, pctSigned } from '@/lib/format'
import styles from './PositionsTable.module.css'

export function PositionsTable({ positions }: { positions: Position[] }) {
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Market · outcome</th>
            <th scope="col" className={styles.num}>
              Value
            </th>
            <th scope="col" className={styles.num}>
              Entry → now
            </th>
            <th scope="col" className={styles.num}>
              Unrealized
            </th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p, i) => (
            <tr key={`${p.conditionId}-${p.outcome}-${i}`}>
              <td className={styles.market}>
                <span className={styles.title}>{p.title}</span>
                <span className={styles.outcome}>{p.outcome}</span>
              </td>
              <td className={`${styles.num} tnum`}>{usd(p.value)}</td>
              <td className={`${styles.num} ${styles.move}`}>
                <span className="tnum">{cents(p.avgPrice)}</span>
                <span className={styles.arrow}>→</span>
                <span className="tnum">{cents(p.curPrice)}</span>
              </td>
              <td className={styles.num}>
                <Value value={p.pnlPct}>{pctSigned(p.pnlPct)}</Value>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
