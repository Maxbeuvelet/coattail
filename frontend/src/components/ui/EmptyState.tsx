/** Honest empty state. Used where a backend phase isn't wired yet — states
 *  plainly what's coming, never fakes data to fill the space. */
import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'
import styles from './EmptyState.module.css'

interface EmptyStateProps {
  icon?: IconName
  title: string
  detail?: ReactNode
  action?: ReactNode
}

export function EmptyState({ icon, title, detail, action }: EmptyStateProps) {
  return (
    <div className={styles.wrap}>
      {icon && (
        <div className={styles.icon}>
          <Icon name={icon} size={20} />
        </div>
      )}
      <div className={styles.title}>{title}</div>
      {detail && <div className={styles.detail}>{detail}</div>}
      {action && <div className={styles.action}>{action}</div>}
    </div>
  )
}
