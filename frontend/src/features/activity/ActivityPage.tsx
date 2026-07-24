/** Activity: the immutable log of what the bot did — copies, exits, and the
 *  trades it deliberately skipped (with the reason). Fed by the engine. */
import { Page } from '@/components/layout/Page'
import { PageHeader } from '@/components/layout/PageHeader'
import { EmptyState } from '@/components/ui/EmptyState'
import { Badge } from '@/components/ui/Badge'
import { Icon, type IconName } from '@/components/ui/Icon'
import { Value } from '@/components/ui/Value'
import { useActivity } from '@/lib/queries'
import { usd, timeAgo, signedUsd2 } from '@/lib/format'
import type { ActivityEntry } from '@/lib/types'
import styles from './ActivityPage.module.css'

const KIND_META: Record<ActivityEntry['kind'], { label: string; icon: IconName; tone: string }> = {
  copy_open: { label: 'Copy', icon: 'plus', tone: styles.open },
  copy_exit: { label: 'Exit', icon: 'check', tone: styles.exit },
  skip: { label: 'Skip', icon: 'alert', tone: styles.skip },
  engine: { label: 'Engine', icon: 'activity', tone: styles.engine },
}

export function ActivityPage() {
  const { data, isLoading } = useActivity(200)
  const rows = data ?? []

  return (
    <Page>
      <PageHeader
        title="Activity"
        subtitle="Every action the engine takes — mirrored entries, exits, and the trades it skipped."
        actions={rows.length > 0 ? <Badge>{rows.length} events</Badge> : undefined}
      />

      {isLoading ? (
        <div className={styles.loading}>Loading activity…</div>
      ) : rows.length === 0 ? (
        <div className={styles.panel}>
          <EmptyState
            icon="activity"
            title="No activity yet"
            detail="The engine writes a line for every decision — copied, exited, or skipped (with the reason: price band, size cap, kill switch). Follow a trader to see it start working."
          />
        </div>
      ) : (
        <ol className={styles.feed}>
          {rows.map((e) => {
            const meta = KIND_META[e.kind]
            return (
              <li key={e.id} className={styles.row}>
                <span className={`${styles.tag} ${meta.tone}`}>
                  <Icon name={meta.icon} size={12} />
                  {meta.label}
                </span>
                <div className={styles.body}>
                  <span className={styles.detail}>{e.detail}</span>
                  {e.title && (
                    <span className={styles.market}>
                      {e.title}
                      {e.outcome && <span className={styles.outcome}>{e.outcome}</span>}
                    </span>
                  )}
                </div>
                <div className={styles.right}>
                  {e.amount != null && e.kind !== 'skip' && (
                    <Value value={e.kind === 'copy_open' ? 0 : e.amount} tone={amountTone(e)}>
                      {e.kind === 'copy_open' ? usd(e.amount) : signedUsd2(e.amount)}
                    </Value>
                  )}
                  <span className={styles.time}>{timeAgo(e.ts)}</span>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </Page>
  )
}

function amountTone(e: ActivityEntry): 'pos' | 'neg' | 'neutral' {
  if (e.kind === 'copy_open') return 'neutral'
  if (e.amount == null) return 'neutral'
  return e.amount >= 0 ? 'pos' : 'neg'
}
