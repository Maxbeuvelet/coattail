/** Compact status/label chip. Hairline border, semantic text — no fills that
 *  shout. */
import type { ReactNode } from 'react'
import styles from './Badge.module.css'

type BadgeTone = 'neutral' | 'live' | 'paper' | 'warn' | 'pos' | 'neg'

interface BadgeProps {
  tone?: BadgeTone
  children: ReactNode
  className?: string
}

export function Badge({ tone = 'neutral', children, className }: BadgeProps) {
  return <span className={`${styles.badge} ${styles[tone]} ${className ?? ''}`}>{children}</span>
}
