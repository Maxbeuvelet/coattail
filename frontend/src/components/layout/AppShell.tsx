/** App frame: fixed sidebar + sticky top bar + scrolling content. */
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import styles from './AppShell.module.css'

export function AppShell() {
  return (
    <div className={styles.shell}>
      <Sidebar />
      <TopBar />
      <main className={styles.content}>
        <Outlet />
      </main>
    </div>
  )
}
