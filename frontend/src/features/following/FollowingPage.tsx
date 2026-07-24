/** Following: the traders you copy (backend-owned list). Enriched with live
 *  leaderboard stats when the trader is in the tracked set. */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Page } from '@/components/layout/Page'
import { PageHeader } from '@/components/layout/PageHeader'
import { EmptyState } from '@/components/ui/EmptyState'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Value } from '@/components/ui/Value'
import { Icon } from '@/components/ui/Icon'
import { api } from '@/lib/api'
import { useOwner } from '@/lib/owner'
import { useFollows } from '@/lib/useFollows'
import { usd, usdCompact, ratioPct, shortAddr } from '@/lib/format'
import type { Trader } from '@/lib/types'
import styles from './FollowingPage.module.css'

export function FollowingPage() {
  const { follows, toggle } = useFollows()
  const { isOwner } = useOwner()

  // Enrich from the full top-50 leaderboard (cheap; one call) so Autopilot's
  // ROI-ranked picks — which sit outside the top-10 — still show their stats.
  const { data: leaders } = useQuery({
    queryKey: ['leaderboard', 'ALL', 50, 'PNL'],
    queryFn: () => api.leaderboard('ALL', 50, 'PNL'),
    staleTime: 60_000,
  })

  const statsByWallet = useMemo(() => {
    const m = new Map<string, Trader>()
    for (const t of leaders ?? []) {
      if (!m.has(t.wallet.toLowerCase())) m.set(t.wallet.toLowerCase(), t as Trader)
    }
    return m
  }, [leaders])

  return (
    <Page>
      <PageHeader
        title="Following"
        subtitle="Traders you copy. The engine mirrors their entries and exits into your book."
        actions={
          follows.length > 0 ? (
            <Badge tone="paper">
              {follows.length} active · engine live
            </Badge>
          ) : undefined
        }
      />

      {follows.length === 0 ? (
        <EmptyState
          icon="users"
          title="You're not following anyone yet"
          detail="Head to Discover, review the leaderboard, and follow the traders whose edge you want to mirror. The engine starts copying them within one tick."
          action={
            <Link to="/discover">
              <Button variant="primary" size="sm">
                <Icon name="compass" size={14} />
                Browse traders
              </Button>
            </Link>
          }
        />
      ) : (
        <div className={styles.list}>
          {follows.map((f) => {
            const t = statsByWallet.get(f.wallet.toLowerCase())
            return (
              <div key={f.wallet} className={styles.card}>
                <div className={styles.identity}>
                  <div className={styles.nameRow}>
                    <span className={styles.name}>{f.name}</span>
                    {f.auto && (
                      <Badge tone="paper">
                        <Icon name="compass" size={11} />
                        Auto
                      </Badge>
                    )}
                    <span className={`${styles.addr} mono`}>{shortAddr(f.wallet)}</span>
                  </div>
                  <div className={styles.meta}>
                    {t ? (
                      <>
                        <span>
                          Profit{' '}
                          <Value value={t.pnl} tone="pos">
                            {usdCompact(t.pnl)}
                          </Value>
                        </span>
                        <span className={styles.dot}>·</span>
                        <span className="tnum">ROI {ratioPct(t.roi)}</span>
                        <span className={styles.dot}>·</span>
                        <span className="tnum">{usdCompact(t.volume)} vol</span>
                      </>
                    ) : (
                      <span className={styles.offboard}>Outside the top 50 by profit</span>
                    )}
                  </div>
                </div>

                <AllocationCell wallet={f.wallet} allocationUsd={f.allocationUsd} readOnly={!isOwner} />

                {isOwner && (
                  <Button variant="ghost" size="sm" onClick={() => toggle(f.wallet, f.name)}>
                    Unfollow
                  </Button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </Page>
  )
}

/** Per-trader position-size override. Blank = fall back to the global cap. */
function AllocationCell({
  wallet,
  allocationUsd,
  readOnly,
}: {
  wallet: string
  allocationUsd: number | null
  readOnly?: boolean
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(allocationUsd != null ? String(allocationUsd) : '')

  const save = useMutation({
    mutationFn: (v: number | null) => api.setAllocation(wallet, v),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['follows'] }),
  })

  const commit = () => {
    const trimmed = value.trim()
    save.mutate(trimmed === '' ? null : Number(trimmed))
    setEditing(false)
  }

  return (
    <div className={styles.alloc}>
      <span className={styles.allocLabel}>Max / position</span>
      {editing ? (
        <span className={styles.allocInputWrap}>
          <span className={styles.allocAffix}>$</span>
          <input
            className={styles.allocInput}
            type="number"
            autoFocus
            placeholder="cap"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit()
              if (e.key === 'Escape') setEditing(false)
            }}
          />
        </span>
      ) : readOnly ? (
        <span className={styles.allocValue}>
          {allocationUsd != null ? usd(allocationUsd) : 'Global cap'}
        </span>
      ) : (
        <button
          className={styles.allocValue}
          onClick={() => setEditing(true)}
          title="Set a per-trader position cap (overrides the global cap)"
        >
          {allocationUsd != null ? usd(allocationUsd) : 'Global cap'}
          <Icon name="chevronDown" size={12} />
        </button>
      )}
    </div>
  )
}
