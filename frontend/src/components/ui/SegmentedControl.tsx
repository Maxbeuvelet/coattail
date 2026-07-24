/** A compact segmented toggle for mutually-exclusive views (window, sort). */
import styles from './SegmentedControl.module.css'

export interface Segment<T extends string> {
  value: T
  label: string
}

interface SegmentedControlProps<T extends string> {
  segments: Segment<T>[]
  value: T
  onChange: (value: T) => void
  ariaLabel: string
}

export function SegmentedControl<T extends string>({
  segments,
  value,
  onChange,
  ariaLabel,
}: SegmentedControlProps<T>) {
  return (
    <div className={styles.group} role="tablist" aria-label={ariaLabel}>
      {segments.map((s) => (
        <button
          key={s.value}
          role="tab"
          aria-selected={s.value === value}
          className={`${styles.seg} ${s.value === value ? styles.on : ''}`}
          onClick={() => onChange(s.value)}
        >
          {s.label}
        </button>
      ))}
    </div>
  )
}
