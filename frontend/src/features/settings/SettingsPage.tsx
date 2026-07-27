/** Settings: risk limits (editable, persisted to the DB, applied live on the
 *  next tick) + the live-trading gate. */
import { useEffect, useMemo, useState } from 'react'
import { Page } from '@/components/layout/Page'
import { PageHeader } from '@/components/layout/PageHeader'
import { StatusDot } from '@/components/ui/StatusDot'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useResetBook, useSettings, useStatus, useUpdateSettings } from '@/lib/queries'
import { useOwner } from '@/lib/owner'
import type { AutopilotRank, RiskConfig, SettingsPatch } from '@/lib/types'
import { ApiError } from '@/lib/api'
import styles from './SettingsPage.module.css'

interface Draft {
  bankrollUsd: string
  maxUsdPerPosition: string
  maxOpenPositions: string
  dailyLossKillPct: string
  priceBandLowPct: string
  priceBandHighPct: string
}

function toDraft(r: RiskConfig): Draft {
  return {
    bankrollUsd: String(r.bankrollUsd),
    maxUsdPerPosition: String(r.maxUsdPerPosition),
    maxOpenPositions: String(r.maxOpenPositions),
    dailyLossKillPct: String(round(r.dailyLossKillPct * 100)),
    priceBandLowPct: String(round(r.priceBand[0] * 100)),
    priceBandHighPct: String(round(r.priceBand[1] * 100)),
  }
}

const round = (n: number) => Math.round(n * 100) / 100

export function SettingsPage() {
  const { data: status } = useStatus()
  const { data: settings } = useSettings()
  const update = useUpdateSettings()
  const { isOwner } = useOwner()
  const live = status?.mode === 'LIVE'

  const [draft, setDraft] = useState<Draft | null>(null)
  useEffect(() => {
    if (settings && draft === null) setDraft(toDraft(settings))
  }, [settings, draft])

  const dirty = useMemo(
    () => (settings && draft ? JSON.stringify(draft) !== JSON.stringify(toDraft(settings)) : false),
    [draft, settings],
  )

  const set = (key: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setDraft((d) => (d ? { ...d, [key]: e.target.value } : d))

  const onSave = () => {
    if (!draft) return
    const patch: SettingsPatch = {
      bankrollUsd: Number(draft.bankrollUsd),
      maxUsdPerPosition: Number(draft.maxUsdPerPosition),
      maxOpenPositions: Number(draft.maxOpenPositions),
      dailyLossKillPct: Number(draft.dailyLossKillPct) / 100,
      priceBandLow: Number(draft.priceBandLowPct) / 100,
      priceBandHigh: Number(draft.priceBandHighPct) / 100,
    }
    update.mutate(patch)
  }

  const paused = settings?.enginePaused ?? false

  return (
    <Page>
      <PageHeader
        title="Settings"
        subtitle="Risk limits apply live on the next engine tick. Your wallet key stays server-side."
      />

      {!isOwner && (
        <div className={styles.readonlyBanner}>
          <Icon name="lock" size={14} />
          Read-only view. Unlock with the owner key (top-right) to change anything.
        </div>
      )}

      {settings && <AutopilotSection autopilot={settings.autopilot} canEdit={isOwner} />}

      {/* ── Trading mode / live gate ── */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>Trading mode</h2>
          <Badge tone={live ? 'live' : 'paper'}>
            <StatusDot tone={live ? 'live' : 'paper'} size={6} pulse={live} />
            {live ? 'Live' : 'Paper'}
          </Badge>
        </div>

        <div className={styles.gate}>
          <div className={styles.gateBody}>
            <p className={styles.gateLead}>
              {live
                ? 'Live trading is ON. Real orders are placed with real funds.'
                : 'Paper mode. Copies are simulated against live prices — no real orders, no risk.'}
            </p>
            <p className={styles.gateDetail}>
              The mode is set by <code>LIVE_TRADING</code> in the backend&apos;s <code>.env</code>,
              not from the browser — a deliberate air-gap so a stray click can never move real money.
              Wallet key is {status?.walletConfigured ? 'configured' : 'not configured'}.
            </p>
          </div>
          <Button variant={live ? 'danger' : 'secondary'} disabled title="Toggling live mode is a Phase 4 action, done deliberately on the backend">
            <Icon name="power" size={14} />
            {live ? 'Disable live' : 'Enable live'}
          </Button>
        </div>

        <div className={styles.pauseRow}>
          <div>
            <span className={styles.pauseLabel}>Engine</span>
            <span className={`${styles.pauseState} ${paused ? styles.pausedText : styles.runningText}`}>
              {paused ? 'Paused — no new copies' : 'Running — copying followed traders'}
            </span>
          </div>
          {isOwner && (
            <Button
              variant={paused ? 'primary' : 'secondary'}
              size="sm"
              disabled={update.isPending}
              onClick={() => update.mutate({ enginePaused: !paused })}
            >
              <Icon name="power" size={13} />
              {paused ? 'Resume engine' : 'Pause engine'}
            </Button>
          )}
        </div>
      </section>

      {/* ── Risk limits (editable) ── */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>Risk limits</h2>
          {dirty && <span className={styles.unsaved}>Unsaved changes</span>}
        </div>

        {draft && (
          <>
            <div className={styles.grid}>
              <NumberField label="Bankroll" prefix="$" value={draft.bankrollUsd} onChange={set('bankrollUsd')} hint="Capital the sizing scales against." disabled={!isOwner} />
              <NumberField label="Max per position" prefix="$" value={draft.maxUsdPerPosition} onChange={set('maxUsdPerPosition')} hint="Fixed cap on any single copied position." disabled={!isOwner} />
              <NumberField label="Max open positions" value={draft.maxOpenPositions} onChange={set('maxOpenPositions')} hint="Portfolio breadth limit." disabled={!isOwner} />
              <NumberField label="Daily-loss kill" suffix="%" value={draft.dailyLossKillPct} onChange={set('dailyLossKillPct')} hint="Halt new copies after this drawdown in a day." disabled={!isOwner} />
              <NumberField label="Price band — low" suffix="%" value={draft.priceBandLowPct} onChange={set('priceBandLowPct')} hint="Skip longshots below this price." disabled={!isOwner} />
              <NumberField label="Price band — high" suffix="%" value={draft.priceBandHighPct} onChange={set('priceBandHighPct')} hint="Skip near-certainties above this price." disabled={!isOwner} />
            </div>

            {update.isError && (
              <p className={styles.error}>
                <Icon name="alert" size={13} />
                {update.error instanceof ApiError ? update.error.message : 'Could not save settings'}
              </p>
            )}

            {isOwner && (
              <div className={styles.actions}>
                <Button variant="ghost" size="sm" disabled={!dirty || update.isPending} onClick={() => settings && setDraft(toDraft(settings))}>
                  Reset
                </Button>
                <Button variant="primary" size="sm" disabled={!dirty || update.isPending} onClick={onSave}>
                  {update.isPending ? 'Saving…' : 'Save changes'}
                </Button>
              </div>
            )}
          </>
        )}
      </section>

      {isOwner && <DangerZone />}
    </Page>
  )
}

const RANK_SEGMENTS = [
  { value: 'churn' as AutopilotRank, label: 'Fast' },
  { value: 'roi' as AutopilotRank, label: 'ROI' },
  { value: 'pnl' as AutopilotRank, label: 'Profit' },
  { value: 'pnl_30d' as AutopilotRank, label: '30-day' },
]

const RANK_LABEL: Record<AutopilotRank, string> = {
  churn: 'fastest-resolving (quick turnover)',
  roi: 'ROI',
  pnl: 'all-time profit',
  pnl_30d: '30-day profit',
}
const COUNT_SEGMENTS = [
  { value: '3', label: 'Top 3' },
  { value: '5', label: 'Top 5' },
  { value: '10', label: 'Top 10' },
]

function AutopilotSection({
  autopilot,
  canEdit,
}: {
  autopilot: import('@/lib/types').Autopilot
  canEdit: boolean
}) {
  const update = useUpdateSettings()
  const on = autopilot.enabled

  return (
    <section className={`${styles.section} ${on ? styles.sectionActive : ''}`}>
      <div className={styles.sectionHead}>
        <h2 className={styles.sectionTitle}>Autopilot</h2>
        {canEdit ? (
          <Button
            variant={on ? 'secondary' : 'primary'}
            size="sm"
            disabled={update.isPending}
            onClick={() => update.mutate({ autopilotEnabled: !on })}
          >
            <StatusDot tone={on ? 'live' : 'idle'} size={6} pulse={on} />
            {on ? 'On' : 'Turn on'}
          </Button>
        ) : (
          <Badge tone={on ? 'live' : 'neutral'}>
            <StatusDot tone={on ? 'live' : 'idle'} size={6} pulse={on} />
            {on ? 'On' : 'Off'}
          </Badge>
        )}
      </div>

      <p className={styles.autoLead}>
        Hands-off mode. Autopilot auto-follows the top{' '}
        <strong>{autopilot.count}</strong> <em>currently-active</em> traders by{' '}
        <strong>{RANK_LABEL[autopilot.rank]}</strong>{' '}
        and copies their positions within your risk limits — keeping the list in sync as the
        leaderboard changes. Traders you follow manually are never touched.
      </p>

      <div className={`${styles.autoControls} ${on && canEdit ? '' : styles.dimmed}`}>
        <div className={styles.control}>
          <span className={styles.controlLabel}>Rank by</span>
          <SegmentedControl
            ariaLabel="Autopilot ranking"
            segments={RANK_SEGMENTS}
            value={autopilot.rank}
            onChange={(v) => update.mutate({ autopilotRank: v })}
          />
        </div>
        <div className={styles.control}>
          <span className={styles.controlLabel}>How many</span>
          <SegmentedControl
            ariaLabel="Autopilot count"
            segments={COUNT_SEGMENTS}
            value={String(autopilot.count)}
            onChange={(v) => update.mutate({ autopilotCount: Number(v) })}
          />
        </div>
      </div>

      {autopilot.rank === 'churn' && (
        <p className={styles.autoNote}>
          <strong>Fast mode:</strong> follows traders loaded with soon-resolving markets and only
          copies positions that settle within ~5 days — so trades close quickly and your Performance
          page fills in fast. Prioritizes turnover for quick feedback, not necessarily the best edge.
        </p>
      )}
      {autopilot.rank === 'roi' && (
        <p className={styles.autoNote}>
          Note: the highest-ROI traders are often flat. Autopilot only follows ones that currently
          hold positions, so there's always something to copy.
        </p>
      )}
    </section>
  )
}

function DangerZone() {
  const reset = useResetBook()
  const [armed, setArmed] = useState(false)

  return (
    <section className={styles.section}>
      <div className={styles.sectionHead}>
        <h2 className={styles.sectionTitle}>Reset</h2>
      </div>
      <div className={styles.gate}>
        <div className={styles.gateBody}>
          <p className={styles.gateLead}>Start over from a clean book</p>
          <p className={styles.gateDetail}>
            Clears all follows, positions and history. Your risk limits and Autopilot settings are
            kept. This can&apos;t be undone.
          </p>
        </div>
        {armed ? (
          <div className={styles.confirmRow}>
            <Button variant="ghost" size="sm" onClick={() => setArmed(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={reset.isPending}
              onClick={() => reset.mutate(undefined, { onSuccess: () => setArmed(false) })}
            >
              {reset.isPending ? 'Resetting…' : 'Confirm reset'}
            </Button>
          </div>
        ) : (
          <Button variant="danger" size="sm" onClick={() => setArmed(true)}>
            Reset book
          </Button>
        )}
      </div>
    </section>
  )
}

interface NumberFieldProps {
  label: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  hint: string
  prefix?: string
  suffix?: string
  disabled?: boolean
}

function NumberField({ label, value, onChange, hint, prefix, suffix, disabled }: NumberFieldProps) {
  return (
    <label className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      <span className={`${styles.inputWrap} ${disabled ? styles.inputDisabled : ''}`}>
        {prefix && <span className={styles.affix}>{prefix}</span>}
        <input
          className={styles.input}
          type="number"
          inputMode="decimal"
          value={value}
          onChange={onChange}
          disabled={disabled}
        />
        {suffix && <span className={`${styles.affix} ${styles.suffix}`}>{suffix}</span>}
      </span>
      <span className={styles.fieldHint}>{hint}</span>
    </label>
  )
}
