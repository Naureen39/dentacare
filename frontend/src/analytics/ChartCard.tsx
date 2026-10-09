import { Download } from 'lucide-react'
import * as React from 'react'

import type { ChartOption } from '@/analytics/options'
import { runtime } from '@/analytics/runtime'
import { Skeleton } from '@/components/ui/display'
import type { ChartTable } from '@/components/ui/chart'
import { EmptyState } from '@/components/ui/navigation'
import { saveFile } from '@/lib/download'
import { cn } from '@/lib/utils'

interface Instance {
  setOption: (option: ChartOption, opts?: object) => void
  resize: () => void
  dispose: () => void
  getDataURL: (opts: object) => string
}

export interface ChartCardProps {
  title: string
  description?: string
  /** The numbers again, for screen readers and for anyone who wants them. */
  table: ChartTable
  option: ChartOption | null
  height?: number
  loading?: boolean
  error?: boolean
  /** Shown instead of the chart when there is nothing to draw. */
  emptyText?: string
  className?: string
  /** Extra content beside the chart, such as a ranked list. */
  aside?: React.ReactNode
}

/**
 * A titled frame for an ECharts chart: loading and empty states, a table of the same numbers
 * (hidden from sight but read by assistive technology, shown on request) and a picture download.
 * The drawing itself is hidden from assistive technology because the table says the same.
 */
export function ChartCard({
  title,
  description,
  table,
  option,
  height = 300,
  loading,
  error,
  emptyText = 'There is nothing to show for these filters.',
  className,
  aside,
}: ChartCardProps) {
  const id = React.useId()
  const host = React.useRef<HTMLDivElement>(null)
  const chart = React.useRef<Instance | null>(null)
  const latest = React.useRef(option)
  const [showTable, setShowTable] = React.useState(false)
  const empty = !loading && !error && (option === null || table.rows.length === 0)
  const drawn = option !== null && !empty && !error

  // Create the chart once the container is on the page, and keep it the size of its container.
  React.useEffect(() => {
    if (!drawn || !host.current) return
    let cancelled = false
    let observer: ResizeObserver | undefined
    void runtime.load().then(({ init }) => {
      if (cancelled || !host.current) return
      chart.current = init(host.current, undefined, { renderer: 'canvas' }) as unknown as Instance
      if (latest.current) chart.current.setOption(latest.current, { notMerge: true })
      observer = new ResizeObserver(() => chart.current?.resize())
      observer.observe(host.current)
    })
    return () => {
      cancelled = true
      observer?.disconnect()
      chart.current?.dispose()
      chart.current = null
    }
    // The chart is rebuilt when it appears or disappears; option changes are applied below.
  }, [drawn])

  React.useEffect(() => {
    latest.current = option
    if (option) chart.current?.setOption(option, { notMerge: true })
  }, [option])

  const download = () => {
    const url = chart.current?.getDataURL({
      type: 'png',
      pixelRatio: 2,
      backgroundColor: '#ffffff',
    })
    if (!url) return
    void fetch(url)
      .then((r) => r.blob())
      .then((blob) => saveFile(blob, `${title.toLowerCase().replace(/\W+/g, '-')}.png`))
  }

  return (
    <figure
      className={cn('rounded-xl border bg-card p-5 shadow-soft', className)}
      aria-labelledby={`${id}-title`}
      aria-busy={loading}
    >
      <figcaption className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={`${id}-title`} className="font-heading text-base font-bold">
            {title}
          </h2>
          {description && <p className="text-sm text-muted-foreground">{description}</p>}
        </div>
        <div className="flex items-center gap-3 text-sm">
          {drawn && (
            <button
              type="button"
              onClick={download}
              className="inline-flex items-center gap-1 rounded-sm font-semibold text-accent-strong hover:text-primary focus-visible:outline-2 focus-visible:outline-ring"
            >
              <Download className="size-4" aria-hidden="true" /> Save picture
              <span className="sr-only"> of {title}</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            aria-expanded={showTable}
            aria-controls={`${id}-table`}
            className="rounded-sm font-semibold text-accent-strong underline underline-offset-2 hover:text-primary focus-visible:outline-2 focus-visible:outline-ring"
          >
            {showTable ? 'Hide data' : 'Show data'}
          </button>
        </div>
      </figcaption>

      {loading && !option ? (
        <Skeleton style={{ height }} className="w-full" />
      ) : error ? (
        <p role="alert" className="rounded-md bg-destructive-soft p-3 text-sm text-destructive">
          We could not load this chart. Please try again.
        </p>
      ) : empty ? (
        <EmptyState title="No data" description={emptyText} className="py-8" />
      ) : (
        <div className={cn(aside && 'grid gap-4 lg:grid-cols-[1fr_260px]')}>
          <div ref={host} aria-hidden="true" style={{ height }} />
          {aside}
        </div>
      )}

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
