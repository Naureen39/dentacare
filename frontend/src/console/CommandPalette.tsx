import { Search } from 'lucide-react'
import * as React from 'react'
import { useNavigate } from 'react-router-dom'

import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { usePatientSearch } from '@/console/api'
import { labelFor, sectionsFor } from '@/console/nav'
import type { Role } from '@/lib/auth'
import { cn } from '@/lib/utils'

interface Entry {
  id: string
  label: string
  hint: string
  to: string
}

/** Ctrl K (or Cmd K): jump to a page, or find a patient by name or email. */
export function CommandPalette({
  open,
  onOpenChange,
  role,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  role: Role
}) {
  const navigate = useNavigate()
  const [query, setQuery] = React.useState('')
  const [active, setActive] = React.useState(0)
  const listId = React.useId()
  const canSearchPatients = role !== 'dentist'
  const needle = query.trim()
  const patients = usePatientSearch(needle, open && canSearchPatients && needle.length >= 2)

  const pages: Entry[] = sectionsFor(role)
    .flatMap((s) => s.items)
    .map((item) => ({
      id: item.to,
      label: labelFor(item, role),
      hint: 'Page',
      to: item.to,
    }))
    .filter((e) => !needle || e.label.toLowerCase().includes(needle.toLowerCase()))
  const people: Entry[] = (needle.length >= 2 ? (patients.data ?? []) : [])
    .slice(0, 8)
    .map((p) => ({
      id: p.id,
      label: `${p.first_name} ${p.last_name}`,
      hint: p.email ?? 'Patient',
      to: `/staff/patients/${p.id}`,
    }))
  const entries = [...people, ...pages]
  const current = Math.min(active, Math.max(entries.length - 1, 0))

  const choose = (entry: Entry | undefined) => {
    if (!entry) return
    onOpenChange(false)
    void navigate(entry.to)
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((current + 1) % Math.max(entries.length, 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((current - 1 + entries.length) % Math.max(entries.length, 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      choose(entries[current])
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        onOpenChange(value)
        if (!value) setQuery('')
      }}
    >
      <DialogContent className="top-24 max-w-xl translate-y-0 gap-0 p-0">
        <DialogTitle className="sr-only">Search</DialogTitle>
        <DialogDescription className="sr-only">
          Type to find a page or a patient by name. Use the arrow keys and Enter to choose.
        </DialogDescription>
        <div className="flex items-center gap-2 border-b px-4">
          <Search className="size-4 text-muted-foreground" aria-hidden="true" />
          <input
            autoFocus
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={entries[current] ? `${listId}-${current}` : undefined}
            aria-label="Search pages and patients"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setActive(0)
            }}
            onKeyDown={onKeyDown}
            placeholder={canSearchPatients ? 'Search pages and patients' : 'Search pages'}
            className="h-12 flex-1 bg-transparent text-base outline-none"
          />
        </div>
        <ul
          id={listId}
          role="listbox"
          aria-label="Results"
          className="max-h-80 overflow-y-auto p-2"
        >
          {entries.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">No results</li>
          )}
          {entries.map((entry, index) => (
            <li
              key={entry.id}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === current}
              onMouseEnter={() => setActive(index)}
              onClick={() => choose(entry)}
              className={cn(
                'flex cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2 text-sm',
                index === current && 'bg-secondary',
              )}
            >
              <span className="font-medium">{entry.label}</span>
              <span className="truncate text-xs text-muted-foreground">{entry.hint}</span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  )
}
