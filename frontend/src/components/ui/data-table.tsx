import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import * as React from 'react'

import { Skeleton } from '@/components/ui/display'
import { EmptyState, Pagination } from '@/components/ui/navigation'
import { cn } from '@/lib/utils'

export interface Column<T> {
  key: string
  header: string
  cell: (row: T) => React.ReactNode
  /** Makes the column sortable: the value rows are compared by. */
  sortValue?: (row: T) => string | number
  align?: 'left' | 'right'
  className?: string
}

export interface DataTableProps<T> {
  /** Names the table for assistive technology. Required. */
  caption: string
  columns: Column<T>[]
  rows: T[]
  getRowId: (row: T) => string
  pageSize?: number
  loading?: boolean
  emptyTitle?: string
  emptyDescription?: string
  /** Height of the scrolling area; the header stays in view inside it. */
  maxHeight?: number
  className?: string
}

type SortState = { key: string; direction: 'asc' | 'desc' } | null

export function compareValues(a: string | number, b: string | number): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), 'en', { numeric: true, sensitivity: 'base' })
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  getRowId,
  pageSize = 10,
  loading = false,
  emptyTitle = 'Nothing to show',
  emptyDescription,
  maxHeight = 480,
  className,
}: DataTableProps<T>) {
  const [sort, setSort] = React.useState<SortState>(null)
  const [page, setPage] = React.useState(1)

  const sorted = React.useMemo(() => {
    if (!sort) return rows
    const column = columns.find((c) => c.key === sort.key)
    if (!column?.sortValue) return rows
    const value = column.sortValue
    const factor = sort.direction === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => factor * compareValues(value(a), value(b)))
  }, [rows, columns, sort])

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize))
  const current = Math.min(page, pageCount)
  const visible = sorted.slice((current - 1) * pageSize, current * pageSize)

  const toggle = (key: string) => {
    setPage(1)
    setSort((state) =>
      state?.key !== key
        ? { key, direction: 'asc' }
        : state.direction === 'asc'
          ? { key, direction: 'desc' }
          : null,
    )
  }

  if (!loading && rows.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} className={className} />
  }

  return (
    <div className={cn('flex flex-col gap-4', className)}>
      <div
        className="overflow-auto rounded-xl border bg-card shadow-soft"
        style={{ maxHeight }}
        role="region"
        aria-label={`${caption}, scrollable`}
        tabIndex={0}
      >
        <table className="w-full border-collapse text-sm" aria-busy={loading || undefined}>
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 z-10 bg-secondary">
            <tr>
              {columns.map((column) => {
                const active = sort?.key === column.key
                const ariaSort = active
                  ? sort.direction === 'asc'
                    ? 'ascending'
                    : 'descending'
                  : column.sortValue
                    ? 'none'
                    : undefined
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={ariaSort}
                    className={cn(
                      'px-4 py-3 text-left font-semibold text-primary',
                      column.align === 'right' && 'text-right',
                    )}
                  >
                    {column.sortValue ? (
                      <button
                        type="button"
                        onClick={() => toggle(column.key)}
                        className={cn(
                          'inline-flex items-center gap-1.5 rounded-sm font-semibold hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-ring',
                          column.align === 'right' && 'flex-row-reverse',
                        )}
                      >
                        {column.header}
                        {active ? (
                          sort.direction === 'asc' ? (
                            <ArrowUp className="size-4" aria-hidden="true" />
                          ) : (
                            <ArrowDown className="size-4" aria-hidden="true" />
                          )
                        ) : (
                          <ArrowUpDown
                            className="size-4 text-muted-foreground"
                            aria-hidden="true"
                          />
                        )}
                        <span className="sr-only">
                          {active
                            ? `, sorted ${sort.direction === 'asc' ? 'ascending' : 'descending'}`
                            : ', not sorted'}
                        </span>
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: Math.min(pageSize, 5) }, (_, i) => (
                  <tr key={i} className="border-t">
                    {columns.map((column) => (
                      <td key={column.key} className="px-4 py-3">
                        <Skeleton className="h-4 w-full max-w-32" />
                      </td>
                    ))}
                  </tr>
                ))
              : visible.map((row) => (
                  <tr key={getRowId(row)} className="border-t transition-colors hover:bg-muted/60">
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          'px-4 py-3',
                          column.align === 'right' && 'text-right tabular-nums',
                          column.className,
                        )}
                      >
                        {column.cell(row)}
                      </td>
                    ))}
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
      {loading && (
        <p className="sr-only" role="status">
          Loading
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {sorted.length === 0
            ? ''
            : `Showing ${(current - 1) * pageSize + 1} to ${Math.min(current * pageSize, sorted.length)} of ${sorted.length}`}
        </p>
        <Pagination
          page={current}
          pageCount={pageCount}
          onPageChange={setPage}
          label={`${caption} pages`}
        />
      </div>
    </div>
  )
}
