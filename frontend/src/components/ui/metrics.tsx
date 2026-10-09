import { ArrowDownRight, ArrowUpRight, Minus, Star } from 'lucide-react'
import * as React from 'react'

import { AnimatedNumber } from '@/components/ui/motion'
import { Card } from '@/components/ui/display'
import { cn } from '@/lib/utils'

// --- Rating ---------------------------------------------------------------------------------

/** Read only stars. The text alternative gives the exact value. */
export function Rating({
  value,
  max = 5,
  className,
}: {
  value: number
  max?: number
  className?: string
}) {
  return (
    <span
      role="img"
      aria-label={`Rated ${value.toFixed(1)} out of ${max}`}
      className={cn('inline-flex items-center gap-0.5', className)}
    >
      {Array.from({ length: max }, (_, i) => {
        const fill = Math.max(0, Math.min(1, value - i))
        return (
          <span key={i} className="relative inline-block size-5" aria-hidden="true">
            <Star className="absolute inset-0 size-5 text-warning" />
            <span className="absolute inset-0 overflow-hidden" style={{ width: `${fill * 100}%` }}>
              <Star className="size-5 fill-warning text-warning" />
            </span>
          </span>
        )
      })}
    </span>
  )
}

/** A rating the visitor can choose: a radio group of stars with a text label for each. */
export function RatingInput({
  value,
  onChange,
  max = 5,
  label = 'Your rating',
}: {
  value: number
  onChange: (value: number) => void
  max?: number
  label?: string
}) {
  const buttons = React.useRef<(HTMLButtonElement | null)[]>([])
  const onKeyDown = (event: React.KeyboardEvent, index: number) => {
    const step =
      event.key === 'ArrowRight' || event.key === 'ArrowUp'
        ? 1
        : event.key === 'ArrowLeft' || event.key === 'ArrowDown'
          ? -1
          : 0
    if (!step) return
    event.preventDefault()
    const next = Math.min(max, Math.max(1, index + 1 + step))
    onChange(next)
    buttons.current[next - 1]?.focus()
  }
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex gap-1">
      {Array.from({ length: max }, (_, i) => {
        const n = i + 1
        return (
          <button
            key={n}
            ref={(node) => {
              buttons.current[i] = node
            }}
            type="button"
            role="radio"
            aria-checked={n === value}
            aria-label={`${n} ${n === 1 ? 'star' : 'stars'}`}
            tabIndex={n === value || (value === 0 && n === 1) ? 0 : -1}
            onClick={() => onChange(n)}
            onKeyDown={(event) => onKeyDown(event, i)}
            className="rounded-sm p-0.5 focus-visible:outline-2 focus-visible:outline-ring"
          >
            <Star
              className={cn('size-7', n <= value ? 'fill-warning text-warning' : 'text-input')}
              aria-hidden="true"
            />
          </button>
        )
      })}
    </div>
  )
}

// --- Sparkline and stat card ----------------------------------------------------------------

export function Sparkline({
  values,
  className,
}: {
  values: (number | null)[]
  className?: string
}) {
  const points = values.filter((v): v is number => v !== null)
  if (points.length < 2) return null
  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = max - min || 1
  const width = 100
  const height = 28
  const path = points
    .map(
      (v, i) =>
        `${(i / (points.length - 1)) * width},${height - 3 - ((v - min) / range) * (height - 6)}`,
    )
    .join(' ')
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={cn('h-8 w-24', className)}
      aria-hidden="true"
      preserveAspectRatio="none"
    >
      <polyline
        points={path}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

export interface StatCardProps {
  label: string
  value: number
  format?: (value: number) => string
  /** The change since the previous period, as a signed number in percent (or points). */
  change?: number | null
  changeUnit?: '%' | ' points'
  /** Set for measures where a fall is good news, such as the no show rate. */
  lowerIsBetter?: boolean
  sparkline?: (number | null)[]
  hint?: string
  className?: string
}

export function StatCard({
  label,
  value,
  format,
  change,
  changeUnit = '%',
  lowerIsBetter,
  sparkline,
  hint,
  className,
}: StatCardProps) {
  const direction = change == null || Math.abs(change) < 0.005 ? 'flat' : change > 0 ? 'up' : 'down'
  const good = direction === 'flat' ? null : (direction === 'up') !== Boolean(lowerIsBetter)
  const Icon = direction === 'up' ? ArrowUpRight : direction === 'down' ? ArrowDownRight : Minus
  return (
    <Card className={cn('flex flex-col gap-3 p-5', className)}>
      <p className="text-sm font-medium text-muted-foreground">{label}</p>
      <p className="font-heading text-3xl font-extrabold text-primary">
        <AnimatedNumber value={value} format={format} />
      </p>
      <div className="flex items-end justify-between gap-2">
        {change === undefined ? (
          <span />
        ) : (
          <p
            className={cn(
              'inline-flex items-center gap-1 text-sm font-semibold',
              good === null && 'text-muted-foreground',
              good === true && 'text-success-strong',
              good === false && 'text-destructive',
            )}
          >
            <Icon className="size-4" aria-hidden="true" />
            <span>
              {change === null
                ? 'No earlier figure'
                : `${change > 0 ? '+' : ''}${change.toFixed(1)}${changeUnit}`}
            </span>
            <span className="sr-only">
              {direction === 'flat' ? ', no change' : direction === 'up' ? ', up' : ', down'}
              {good === null ? '' : good ? ', which is better' : ', which is worse'}
            </span>
          </p>
        )}
        {sparkline && <Sparkline values={sparkline} className="text-accent-strong" />}
      </div>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </Card>
  )
}
