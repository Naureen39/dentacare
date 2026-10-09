import * as React from 'react'
import { ResponsiveContainer } from 'recharts'

import { cn } from '@/lib/utils'

/** Series colours, in order. Each is distinguishable from white and from its neighbours. */
export const chartColors = [
  '#0b2545',
  '#0b7371',
  '#e39b1d',
  '#d64545',
  '#1e9e6a',
  '#6b7a99',
] as const

export interface ChartTable {
  columns: string[]
  rows: (string | number)[][]
}

export interface ChartProps {
  title: string
  description?: string
  /** The data again as a table, read by screen readers and shown on request. */
  table: ChartTable
  height?: number
  /** The chart itself, a recharts chart such as a LineChart. */
  children: React.ReactElement
  className?: string
}

/**
 * A titled, responsive frame for a chart. A chart is a picture, so the same numbers are given as
 * a table: it is hidden visually but available to assistive technology, and "Show data" reveals
 * it to everyone.
 */
export function Chart({
  title,
  description,
  table,
  height = 288,
  children,
  className,
}: ChartProps) {
  const [showTable, setShowTable] = React.useState(false)
  const id = React.useId()
  return (
    <figure
      className={cn('rounded-xl border bg-card p-5 shadow-soft', className)}
      aria-labelledby={`${id}-title`}
    >
      <figcaption className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 id={`${id}-title`} className="font-heading text-base font-bold">
            {title}
          </h3>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
        <button
          type="button"
          onClick={() => setShowTable((v) => !v)}
          aria-expanded={showTable}
          aria-controls={`${id}-table`}
          className="rounded-sm text-sm font-semibold text-accent-strong underline underline-offset-2 hover:text-primary focus-visible:outline-2 focus-visible:outline-ring"
        >
          {showTable ? 'Hide data' : 'Show data'}
        </button>
      </figcaption>
      <div aria-hidden="true" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          {/* The picture is hidden from assistive technology (the table replaces it), so its
              own keyboard layer is turned off too: focus must not land inside hidden content. */}
          {React.cloneElement(children, { accessibilityLayer: false } as object)}
        </ResponsiveContainer>
      </div>
      <div id={`${id}-table`} className={cn('mt-4 overflow-x-auto', !showTable && 'sr-only')}>
        <table className="w-full text-sm">
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th key={column} scope="col" className="px-3 py-2 text-left font-semibold">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, i) => (
              <tr key={i} className="border-t">
                {row.map((cell, j) =>
                  j === 0 ? (
                    <th key={j} scope="row" className="px-3 py-2 text-left font-medium">
                      {cell}
                    </th>
                  ) : (
                    <td key={j} className="px-3 py-2">
                      {cell}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}
