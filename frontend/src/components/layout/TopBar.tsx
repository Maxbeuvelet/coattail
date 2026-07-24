/** Global top bar: connection, live/paper mode, engine run-state, and the
 *  always-reachable pause control (the hard kill lands with live in Phase 4). */
import { useStatus, useUpdateSettings } from '@/lib/queries'
import { useOwner } from '@/lib/owner'
import { StatusDot } from '@/components/ui/StatusDot'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import styles from './TopBar.module.css'

export function TopBar() {
  const { data: status, isError } = useStatus()
  const update = useUpdateSettings()
  const { isOwner, authRequired, unlock, lock } = useOwner()
  const live = status?.mode === 'LIVE'
  const paused = status?.engine.paused ?? false

  const promptUnlock = () => {
    const key = window.prompt('Enter owner key to enable controls')
    if (key) unlock(key)
  }

  return (
    <header className={styles.bar}>
      <div className={styles.left}>
        <div className={styles.connection}>
          <StatusDot
            tone={isError ? 'neg' : 'live'}
            pulse={!isError}
            title={isError ? 'Backend unreachable' : 'Connected to backend'}
          />
          <span className={styles.connLabel}>{isError ? 'Disconnected' : 'Connected'}</span>
        </div>
        <span className={styles.divider} />
        <span className={styles.env}>Polymarket · Polygon</span>
      </div>

      <div className={styles.right}>
        {status?.autopilot.enabled && (
          <Badge tone="paper">
            <Icon name="compass" size={12} />
            Autopilot · top {status.autopilot.count}
          </Badge>
        )}
        {status && (
          <Badge tone={live ? 'live' : 'paper'}>
            <StatusDot tone={live ? 'live' : 'paper'} size={6} pulse={live} />
            {live ? 'Live trading' : 'Paper mode'}
          </Badge>
        )}
        {paused && (
          <Badge tone="warn">
            <Icon name="alert" size={12} />
            Engine paused
          </Badge>
        )}

        {/* Read-only visitors get an unlock affordance; the owner gets controls. */}
        {authRequired && !isOwner ? (
          <Button variant="secondary" size="sm" onClick={promptUnlock} title="Enter owner key">
            <Icon name="lock" size={13} />
            Read-only
          </Button>
        ) : (
          <>
            {authRequired && (
              <button className={styles.ownerChip} onClick={lock} title="Lock controls (switch to read-only)">
                <Icon name="unlock" size={13} />
              </button>
            )}
            <Button
              variant={paused ? 'secondary' : 'danger'}
              size="sm"
              disabled={!status || update.isPending}
              onClick={() => update.mutate({ enginePaused: !paused })}
              title={paused ? 'Resume copying' : 'Pause all new copies immediately'}
            >
              <Icon name="power" size={14} />
              {paused ? 'Resume' : 'Pause'}
            </Button>
          </>
        )}
      </div>
    </header>
  )
}
