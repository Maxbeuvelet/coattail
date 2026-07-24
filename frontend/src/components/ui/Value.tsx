/** Renders a number with P&L semantics: green up, red down, quiet at zero.
 *  Always tabular. This is the single place sign→color is decided. */
import { signOf } from '@/lib/format'
import styles from './Value.module.css'

interface ValueProps {
  /** The numeric value whose sign drives color (unless `tone` overrides). */
  value: number
  /** Preformatted display string; falls back to the raw number. */
  children?: React.ReactNode
  /** Force a tone regardless of sign. */
  tone?: 'pos' | 'neg' | 'zero' | 'neutral'
  /** Neutral never colors — for plain magnitudes (volume, value). */
  colorize?: boolean
  className?: string
}

export function Value({ value, children, tone, colorize = true, className }: ValueProps) {
  const resolved = tone ?? (colorize ? signOf(value) : 'neutral')
  return (
    <span className={`${styles.value} ${styles[resolved]} tnum ${className ?? ''}`}>
      {children ?? value}
    </span>
  )
}
