/** Consistent content padding + max measure for every route. */
import type { ReactNode } from 'react'
import styles from './Page.module.css'

export function Page({ children }: { children: ReactNode }) {
  return <div className={styles.page}>{children}</div>
}
