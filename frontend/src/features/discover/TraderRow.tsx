/** One leaderboard row + its expandable open book. */
import type { KeyboardEvent } from 'react'
import type { Trader } from '@/lib/types'
import { Value } from '@/components/ui/Value'
import { Icon } from '@/components/ui/Icon'
import { useFollows } from '@/lib/useFollows'
import { useOwner } from '@/lib/owner'
import { usdCompact, ratioPct, shortAddr } from '@/lib/format'
import { PositionsTable } from './PositionsTable'
import styles from './LeaderboardTable.module.css'

interface TraderRowProps {
  trader: Trader
  maxPnl: number
  expanded: boolean
  onToggle: () => void
}

export function TraderRow({ trader, maxPnl, expanded, onToggle }: TraderRowProps) {
  const { isFollowing, toggle } = useFollows()
  const { isOwner } = useOwner()
  const following = isFollowing(trader.wallet)
  const hasPositions = trader.positions.length > 0
  const barPct = Math.max(1.5, (trader.pnl / maxPnl) * 100)

  const onKey = (e: KeyboardEvent<HTMLTableRowElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onToggle()
    }
  }

  return (
    <tbody className={`${styles.group} ${expanded ? styles.groupOpen : ''}`}>
      <tr
        className={styles.row}
        onClick={onToggle}
        onKeyDown={onKey}
        tabIndex={0}
        role="button"
        aria-expanded={expanded}
      >
        <td className={styles.colRank}>
          <span className={`${styles.rank} ${trader.rank <= 3 ? styles.rankTop : ''}`}>
            {trader.rank}
          </span>
        </td>

        <td className={styles.colTrader}>
          <div className={styles.trader}>
            <span className={styles.name}>{trader.name}</span>
            <span className={`${styles.addr} mono`}>{shortAddr(trader.wallet)}</span>
          </div>
        </td>

        <td className={styles.colNum}>
          {/* In-cell magnitude bar sits behind the number — scan + read. */}
          <span className={styles.bar} style={{ width: `${barPct}%` }} aria-hidden="true" />
          <Value value={trader.pnl} tone="pos" className={styles.pnl}>
            {usdCompact(trader.pnl)}
          </Value>
        </td>

        <td className={styles.colNum}>
          <span className="tnum">{ratioPct(trader.roi)}</span>
        </td>

        <td className={`${styles.colNum} ${styles.hideSm}`}>
          <span className={`tnum ${styles.muted}`}>{usdCompact(trader.volume)}</span>
        </td>

        <td className={`${styles.colNum} ${styles.hideSm}`}>
          {hasPositions ? (
            <span className="tnum">{usdCompact(trader.openExposure)}</span>
          ) : (
            <span className={styles.flat}>flat</span>
          )}
        </td>

        <td className={styles.colFollow}>
          {isOwner ? (
            <button
              className={`${styles.follow} ${following ? styles.followOn : ''}`}
              onClick={(e) => {
                e.stopPropagation()
                toggle(trader.wallet, trader.name)
              }}
              aria-pressed={following}
              title={following ? `Unfollow ${trader.name}` : `Follow ${trader.name}`}
            >
              <Icon name={following ? 'check' : 'plus'} size={13} />
              {following ? 'Following' : 'Follow'}
            </button>
          ) : following ? (
            <span className={`${styles.follow} ${styles.followOn}`}>
              <Icon name="check" size={13} />
              Following
            </span>
          ) : null}
        </td>

        <td className={styles.colChev}>
          <Icon
            name="chevronRight"
            size={14}
            className={`${styles.chev} ${expanded ? styles.chevOpen : ''}`}
          />
        </td>
      </tr>

      {expanded && (
        <tr className={styles.detailRow}>
          <td colSpan={8} className={styles.detailCell}>
            {hasPositions ? (
              <PositionsTable positions={trader.positions} />
            ) : (
              <p className={styles.noPositions}>
                No open positions — this trader is currently flat (all bets settled or
                redeemed). Nothing to copy right now.
              </p>
            )}
          </td>
        </tr>
      )}
    </tbody>
  )
}
