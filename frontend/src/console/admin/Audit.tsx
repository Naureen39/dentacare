import { Download } from 'lucide-react'
import * as React from 'react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/display'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { EmptyState } from '@/components/ui/navigation'
import { fetchAuditCsv, PAGE, useAuditLogs } from '@/console/api'
import { FormAlert } from '@/lib/auth-forms'
import { saveFile } from '@/lib/download'
import { clock, longDay } from '@/pages/portal/format'

export function AuditPage() {
  const [action, setAction] = React.useState('')
  const [since, setSince] = React.useState('')
  const [until, setUntil] = React.useState('')
  const [offset, setOffset] = React.useState(0)
  const [problem, setProblem] = React.useState<string>()
  const filters = {
    action: action.trim() || undefined,
    since: since || undefined,
    until: until || undefined,
  }
  const logs = useAuditLogs({ ...filters, offset })

  const reset = () => setOffset(0)
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl">Audit log</h1>
        <Button
          variant="secondary"
          onClick={async () => {
            setProblem(undefined)
            try {
              saveFile(await fetchAuditCsv(filters), 'audit-log.csv', 'text/csv')
            } catch {
              setProblem('We could not export the log. Please try again.')
            }
          }}
        >
          <Download aria-hidden="true" /> Export CSV
        </Button>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        Who did what, and when. Viewing and exporting this log is itself recorded.
      </p>
      <FormAlert message={problem} />
      <form
        className="mt-4 grid gap-4 sm:grid-cols-3"
        aria-label="Filter the audit log"
        onSubmit={(event) => event.preventDefault()}
      >
        <Field label="Action" hint="For example auth.login or appointment.status">
          {(c) => (
            <Input
              {...c}
              value={action}
              onChange={(e) => {
                setAction(e.target.value)
                reset()
              }}
            />
          )}
        </Field>
        <Field label="From">
          {(c) => (
            <Input
              {...c}
              type="date"
              value={since}
              onChange={(e) => {
                setSince(e.target.value)
                reset()
              }}
            />
          )}
        </Field>
        <Field label="To">
          {(c) => (
            <Input
              {...c}
              type="date"
              value={until}
              onChange={(e) => {
                setUntil(e.target.value)
                reset()
              }}
            />
          )}
        </Field>
      </form>

      <div className="mt-6">
        {logs.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : !logs.data?.length ? (
          <EmptyState title="Nothing recorded" description="No entries match these filters." />
        ) : (
          <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Audit entries, newest first</caption>
              <thead className="bg-muted text-xs uppercase">
                <tr>
                  <th scope="col" className="p-3">
                    When
                  </th>
                  <th scope="col" className="p-3">
                    Who
                  </th>
                  <th scope="col" className="p-3">
                    Action
                  </th>
                  <th scope="col" className="p-3">
                    About
                  </th>
                </tr>
              </thead>
              <tbody>
                {logs.data.map((e) => (
                  <tr key={e.id} className="border-t align-top">
                    <td className="p-3 whitespace-nowrap">
                      {longDay(e.created_at)} {clock(e.created_at)}
                    </td>
                    <td className="p-3">{e.actor_role ?? 'system'}</td>
                    <td className="p-3 font-mono text-xs">{e.action}</td>
                    <td className="p-3 text-muted-foreground">
                      {e.entity ?? ''}{' '}
                      {Object.keys(e.metadata).length ? JSON.stringify(e.metadata) : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="mt-4 flex items-center justify-between">
        <Button
          variant="secondary"
          size="sm"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE))}
        >
          Newer
        </Button>
        <span className="text-sm text-muted-foreground">
          Entries {offset + 1} to {offset + (logs.data?.length ?? 0)}
        </span>
        <Button
          variant="secondary"
          size="sm"
          disabled={(logs.data?.length ?? 0) < PAGE}
          onClick={() => setOffset(offset + PAGE)}
        >
          Older
        </Button>
      </div>
    </div>
  )
}
