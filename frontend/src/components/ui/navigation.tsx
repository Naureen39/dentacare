import { Check, ChevronLeft, ChevronRight, ChevronRight as Separator } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'

import { cn } from '@/lib/utils'

// --- Breadcrumbs ----------------------------------------------------------------------------

export interface Crumb {
  label: string
  /** Leave out for the current page. */
  to?: string
}

export function Breadcrumbs({ items, className }: { items: Crumb[]; className?: string }) {
  return (
    <nav aria-label="Breadcrumb" className={className}>
      <ol className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
        {items.map((item, index) => {
          const last = index === items.length - 1
          return (
            <li key={`${item.label}-${index}`} className="flex items-center gap-1.5">
              {item.to && !last ? (
                <Link
                  to={item.to}
                  className="rounded-sm font-medium text-accent-strong underline-offset-2 hover:underline"
                >
                  {item.label}
                </Link>
              ) : (
                <span
                  aria-current={last ? 'page' : undefined}
                  className={cn(last && 'font-semibold text-primary')}
                >
                  {item.label}
                </span>
              )}
              {!last && <Separator className="size-4" aria-hidden="true" />}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

// --- Pagination -----------------------------------------------------------------------------

/** The page numbers to show: always the first and last, the current page and its neighbours. */
export function pageItems(page: number, count: number): (number | 'gap')[] {
  if (count <= 7) return Array.from({ length: count }, (_, i) => i + 1)
  const wanted = new Set([1, 2, count - 1, count, page - 1, page, page + 1])
  const pages = [...wanted].filter((p) => p >= 1 && p <= count).sort((a, b) => a - b)
  const out: (number | 'gap')[] = []
  pages.forEach((p, i) => {
    const previous = pages[i - 1]
    if (previous !== undefined && p - previous > 1) out.push('gap')
    out.push(p)
  })
  return out
}

export interface PaginationProps {
  page: number
  pageCount: number
  onPageChange: (page: number) => void
  /** Names the navigation. Give each one on a page a different name. */
  label?: string
  className?: string
}

export function Pagination({
  page,
  pageCount,
  onPageChange,
  label = 'Pagination',
  className,
}: PaginationProps) {
  if (pageCount <= 1) return null
  const button =
    'inline-flex size-10 items-center justify-center rounded-full text-sm font-medium transition-colors hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-40'
  return (
    <nav aria-label={label} className={cn('flex items-center justify-center gap-1', className)}>
      <button
        type="button"
        className={button}
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        aria-label="Previous page"
      >
        <ChevronLeft className="size-5" aria-hidden="true" />
      </button>
      {pageItems(page, pageCount).map((item, index) =>
        item === 'gap' ? (
          <span key={`gap-${index}`} className="px-1 text-muted-foreground" aria-hidden="true">
            ...
          </span>
        ) : (
          <button
            key={item}
            type="button"
            className={cn(
              button,
              item === page && 'bg-primary text-primary-foreground hover:bg-primary',
            )}
            aria-label={`Page ${item}`}
            aria-current={item === page ? 'page' : undefined}
            onClick={() => onPageChange(item)}
          >
            {item}
          </button>
        ),
      )}
      <button
        type="button"
        className={button}
        disabled={page >= pageCount}
        onClick={() => onPageChange(page + 1)}
        aria-label="Next page"
      >
        <ChevronRight className="size-5" aria-hidden="true" />
      </button>
    </nav>
  )
}

// --- Stepper --------------------------------------------------------------------------------

export interface StepperProps {
  steps: string[]
  /** Zero based index of the step the visitor is on. */
  current: number
  className?: string
}

export function Stepper({ steps, current, className }: StepperProps) {
  return (
    <nav aria-label="Progress" className={className}>
      <ol className="flex w-full items-start">
        {steps.map((step, index) => {
          const done = index < current
          const active = index === current
          return (
            <li
              key={step}
              aria-current={active ? 'step' : undefined}
              className="relative flex flex-1 flex-col items-center gap-2 text-center after:absolute after:top-4 after:left-[calc(50%+1.25rem)] after:h-0.5 after:w-[calc(100%-2.5rem)] after:bg-border last:after:hidden data-[done=true]:after:bg-accent-strong"
              data-done={done}
            >
              <span
                className={cn(
                  'z-10 flex size-8 items-center justify-center rounded-full border-2 bg-card text-sm font-semibold',
                  done && 'border-accent-strong bg-accent-strong text-white',
                  active && 'border-primary text-primary',
                  !done && !active && 'border-input text-muted-foreground',
                )}
              >
                {done ? <Check className="size-4" aria-hidden="true" /> : index + 1}
                <span className="sr-only">{done ? ' completed' : active ? ' current' : ''}</span>
              </span>
              <span
                className={cn(
                  'text-xs font-medium sm:text-sm',
                  active ? 'text-primary' : 'text-muted-foreground',
                )}
              >
                {step}
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

// --- Empty state ----------------------------------------------------------------------------

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-6 py-12 text-center',
        className,
      )}
    >
      {icon && (
        <div className="flex size-12 items-center justify-center rounded-full bg-secondary text-accent-strong">
          {icon}
        </div>
      )}
      <h3 className="font-heading text-lg font-bold">{title}</h3>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action}
    </div>
  )
}
