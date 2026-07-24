/** Equity curve — cumulative realized equity per closed trade. Single series,
 *  colored by net result, with the starting-bankroll baseline and a hover
 *  readout. Hand-built SVG (no chart lib) for full control over the marks. */
import { useMemo, useRef, useState } from 'react'
import type { EquityPoint } from '@/lib/types'
import { usd, signedUsd2 } from '@/lib/format'
import styles from './EquityCurve.module.css'

const W = 760
const H = 260
const PAD = { l: 12, r: 14, t: 18, b: 24 }

interface EquityCurveProps {
  points: EquityPoint[]
  baseline: number
}

export function EquityCurve({ points, baseline }: EquityCurveProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [hover, setHover] = useState<number | null>(null)

  const geo = useMemo(() => {
    const plotW = W - PAD.l - PAD.r
    const plotH = H - PAD.t - PAD.b
    const equities = points.map((p) => p.equity)
    const lo = Math.min(baseline, ...equities)
    const hi = Math.max(baseline, ...equities)
    const span = hi - lo || 1
    const padY = span * 0.12
    const ymin = lo - padY
    const ymax = hi + padY

    const x = (i: number) => PAD.l + (points.length === 1 ? 0 : (i / (points.length - 1)) * plotW)
    const y = (v: number) => PAD.t + (1 - (v - ymin) / (ymax - ymin)) * plotH

    const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`).join(' ')
    const area = `${line} L${x(points.length - 1).toFixed(1)},${(H - PAD.b).toFixed(1)} L${x(0).toFixed(1)},${(H - PAD.b).toFixed(1)} Z`
    return { x, y, line, area, ymin, ymax, baselineY: y(baseline) }
  }, [points, baseline])

  const last = points[points.length - 1]
  const net = last.equity - baseline
  const up = net >= 0
  const tone = up ? 'var(--pos)' : 'var(--neg)'

  const onMove = (e: React.MouseEvent) => {
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const frac = (e.clientX - rect.left) / rect.width
    const i = Math.round(frac * (points.length - 1))
    setHover(Math.max(0, Math.min(points.length - 1, i)))
  }

  const hoverP = hover != null ? points[hover] : null

  return (
    <div className={styles.wrap}>
      <div className={styles.readout}>
        <span className={styles.roValue} style={{ color: tone }}>
          {hoverP ? usd(hoverP.equity) : usd(last.equity)}
        </span>
        <div className={styles.roMeta}>
          <span className={styles.roLabel}>
            {hoverP
              ? `${hoverP.t ? new Date(hoverP.t).toLocaleDateString() : 'Start'} · trade ${hover}`
              : `Now · ${points.length - 1} closed`}
          </span>
          <span className={styles.roSub}>
            {hoverP ? `${signedUsd2(hoverP.realized)} realized` : `${signedUsd2(net)} vs start`}
          </span>
        </div>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className={styles.svg}
        preserveAspectRatio="none"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label="Equity curve over closed trades"
      >
        <defs>
          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={tone} stopOpacity="0.16" />
            <stop offset="100%" stopColor={tone} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* starting-bankroll baseline */}
        <line
          x1={PAD.l}
          x2={W - PAD.r}
          y1={geo.baselineY}
          y2={geo.baselineY}
          className={styles.baseline}
        />
        <text x={W - PAD.r} y={geo.baselineY - 5} className={styles.baselineLabel} textAnchor="end">
          start · {usd(baseline)}
        </text>

        <path d={geo.area} fill="url(#eqFill)" />
        <path d={geo.line} fill="none" stroke={tone} strokeWidth={2} vectorEffect="non-scaling-stroke" />

        {/* hover crosshair + marker */}
        {hoverP && hover != null && (
          <>
            <line
              x1={geo.x(hover)}
              x2={geo.x(hover)}
              y1={PAD.t}
              y2={H - PAD.b}
              className={styles.crosshair}
            />
            <circle cx={geo.x(hover)} cy={geo.y(hoverP.equity)} r={3.5} fill={tone} stroke="var(--surface-1)" strokeWidth={1.5} />
          </>
        )}
      </svg>
    </div>
  )
}
