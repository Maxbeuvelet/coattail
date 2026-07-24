/** A small state dot. Optional slow pulse for "live" — subtle, not flashy. */
import styles from './StatusDot.module.css'

type DotTone = 'live' | 'paper' | 'warn' | 'neg' | 'idle'

interface StatusDotProps {
  tone: DotTone
  pulse?: boolean
  size?: number
  title?: string
}

export function StatusDot({ tone, pulse = false, size = 7, title }: StatusDotProps) {
  return (
    <span
      className={`${styles.dot} ${styles[tone]} ${pulse ? styles.pulse : ''}`}
      style={{ width: size, height: size }}
      title={title}
      role={title ? 'img' : undefined}
      aria-label={title}
    />
  )
}
