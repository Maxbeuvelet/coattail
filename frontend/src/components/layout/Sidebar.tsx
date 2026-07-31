/** Left navigation rail. Efficient, quiet, always visible on desktop. */
import { NavLink } from 'react-router-dom'
import { Icon, type IconName } from '@/components/ui/Icon'
import { useFollows } from '@/lib/useFollows'
import styles from './Sidebar.module.css'

interface NavItem {
  to: string
  label: string
  icon: IconName
  /** Optional live count badge (e.g. followed traders). */
  badge?: number
}

export function Sidebar() {
  const { count } = useFollows()

  const items: NavItem[] = [
    { to: '/discover', label: 'Discover', icon: 'compass' },
    { to: '/following', label: 'Following', icon: 'users', badge: count || undefined },
    { to: '/book', label: 'Book', icon: 'wallet' },
    { to: '/us-book', label: 'US book', icon: 'trending' },
    { to: '/performance', label: 'Performance', icon: 'trending' },
    { to: '/activity', label: 'Activity', icon: 'activity' },
    { to: '/settings', label: 'Settings', icon: 'settings' },
  ]

  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <span className={styles.mark} aria-hidden="true" />
        <span className={styles.wordmark}>
          coattail<span className={styles.dim}>.net</span>
        </span>
      </div>

      <nav className={styles.nav} aria-label="Primary">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `${styles.link} ${isActive ? styles.active : ''}`}
          >
            <Icon name={item.icon} size={16} />
            <span className={styles.linkLabel}>{item.label}</span>
            {item.badge != null && <span className={`${styles.count} tnum`}>{item.badge}</span>}
          </NavLink>
        ))}
      </nav>

      <div className={styles.foot}>
        <span className={styles.footText}>Read-only until you go live</span>
      </div>
    </aside>
  )
}
