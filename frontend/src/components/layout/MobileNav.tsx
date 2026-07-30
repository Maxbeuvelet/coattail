/** Horizontal nav strip shown only on mobile (the sidebar is hidden there).
 *  Scrolls sideways if the tabs don't fit, so every page stays reachable. */
import { NavLink } from 'react-router-dom'
import { Icon, type IconName } from '@/components/ui/Icon'
import { useFollows } from '@/lib/useFollows'
import styles from './MobileNav.module.css'

interface NavItem {
  to: string
  label: string
  icon: IconName
  badge?: number
}

export function MobileNav() {
  const { count } = useFollows()

  const items: NavItem[] = [
    { to: '/discover', label: 'Discover', icon: 'compass' },
    { to: '/following', label: 'Following', icon: 'users', badge: count || undefined },
    { to: '/book', label: 'Book', icon: 'wallet' },
    { to: '/performance', label: 'Performance', icon: 'trending' },
    { to: '/activity', label: 'Activity', icon: 'activity' },
    { to: '/settings', label: 'Settings', icon: 'settings' },
  ]

  return (
    <nav className={styles.nav} aria-label="Primary (mobile)">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) => `${styles.tab} ${isActive ? styles.active : ''}`}
        >
          <Icon name={item.icon} size={16} />
          <span className={styles.label}>{item.label}</span>
          {item.badge != null && <span className={`${styles.count} tnum`}>{item.badge}</span>}
        </NavLink>
      ))}
    </nav>
  )
}
