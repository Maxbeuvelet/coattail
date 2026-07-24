/** Inline stroke icons (16px grid, 1.5 stroke). A tiny hand-picked set — no
 *  icon-font dependency, no emoji. Add paths as needed. */
import type { ReactElement, SVGProps } from 'react'

export type IconName =
  | 'compass'
  | 'users'
  | 'wallet'
  | 'activity'
  | 'settings'
  | 'chevronRight'
  | 'chevronDown'
  | 'arrowUpDown'
  | 'plus'
  | 'check'
  | 'power'
  | 'dot'
  | 'external'
  | 'alert'
  | 'search'
  | 'trending'
  | 'lock'
  | 'unlock'

const PATHS: Record<IconName, ReactElement> = {
  compass: (
    <>
      <circle cx="8" cy="8" r="6.25" />
      <path d="M10.8 5.2 9.4 9.4 5.2 10.8 6.6 6.6z" />
    </>
  ),
  users: (
    <>
      <path d="M10.5 13.5v-1a2.5 2.5 0 0 0-2.5-2.5H4.5A2.5 2.5 0 0 0 2 12.5v1" />
      <circle cx="6.25" cy="5" r="2.25" />
      <path d="M14 13.5v-1a2.5 2.5 0 0 0-1.9-2.42M10.5 2.65A2.25 2.25 0 0 1 10.5 7" />
    </>
  ),
  wallet: (
    <>
      <rect x="2" y="3.5" width="12" height="9" rx="1.5" />
      <path d="M2 6.5h12M11 9.75h.6" />
    </>
  ),
  activity: <path d="M1.5 8h3l1.75 4.5L9.25 3l1.75 5h3.5" />,
  settings: (
    <>
      <circle cx="8" cy="8" r="2" />
      <path d="M8 1.5v1.6M8 12.9v1.6M14.5 8h-1.6M3.1 8H1.5M12.6 3.4l-1.1 1.1M4.5 11.5l-1.1 1.1M12.6 12.6l-1.1-1.1M4.5 4.5 3.4 3.4" />
    </>
  ),
  chevronRight: <path d="M6 3.5 10.5 8 6 12.5" />,
  chevronDown: <path d="M3.5 6 8 10.5 12.5 6" />,
  arrowUpDown: <path d="M4.5 6 4.5 2.5M4.5 2.5 2.75 4.25M4.5 2.5 6.25 4.25M11.5 10v3.5M11.5 13.5l1.75-1.75M11.5 13.5 9.75 11.75" />,
  plus: <path d="M8 3.5v9M3.5 8h9" />,
  check: <path d="M3 8.5 6.5 12 13 4.5" />,
  power: (
    <>
      <path d="M8 2v6" />
      <path d="M4.4 4.6a5 5 0 1 0 7.2 0" />
    </>
  ),
  dot: <circle cx="8" cy="8" r="3" fill="currentColor" stroke="none" />,
  external: (
    <>
      <path d="M9 3.5h3.5V7" />
      <path d="M12.5 3.5 7 9" />
      <path d="M11 9v2.5A1.5 1.5 0 0 1 9.5 13h-5A1.5 1.5 0 0 1 3 11.5v-5A1.5 1.5 0 0 1 4.5 5H7" />
    </>
  ),
  alert: (
    <>
      <path d="M8 2.5 14.5 13.5H1.5z" />
      <path d="M8 6.5v3.2M8 11.6h.01" />
    </>
  ),
  search: (
    <>
      <circle cx="7" cy="7" r="4.25" />
      <path d="M10.2 10.2 13.5 13.5" />
    </>
  ),
  trending: (
    <>
      <path d="M1.5 11 6 6.5 8.5 9 14.5 3" />
      <path d="M10.5 3h4v4" />
    </>
  ),
  lock: (
    <>
      <rect x="3" y="7" width="10" height="6.5" rx="1.5" />
      <path d="M5 7V5a3 3 0 0 1 6 0v2" />
    </>
  ),
  unlock: (
    <>
      <rect x="3" y="7" width="10" height="6.5" rx="1.5" />
      <path d="M5 7V5a3 3 0 0 1 5.8-1" />
    </>
  ),
}

interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: IconName
  size?: number
}

export function Icon({ name, size = 16, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  )
}
