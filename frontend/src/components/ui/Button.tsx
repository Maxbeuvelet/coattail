/** Intentional buttons. Three variants, one size scale. Nothing decorative. */
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import styles from './Button.module.css'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  active?: boolean
  children: ReactNode
}

export function Button({
  variant = 'secondary',
  size = 'md',
  active = false,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`${styles.btn} ${styles[variant]} ${styles[size]} ${
        active ? styles.active : ''
      } ${className ?? ''}`}
      {...rest}
    >
      {children}
    </button>
  )
}
