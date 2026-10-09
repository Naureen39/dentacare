import { ChevronDown } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

export interface NavDisclosureProps {
  label: string
  /** Classes for the panel that opens under the button. */
  panelClassName?: string
  /** True when the current page is inside this menu. */
  active?: boolean
  children: (close: () => void) => React.ReactNode
}

/**
 * A menu button that opens a panel of links. It opens on click, on keyboard activation, and when
 * a mouse rests on it. Escape closes it and returns focus to the button, and so do a click
 * elsewhere or tabbing out of the panel.
 */
export function NavDisclosure({ label, panelClassName, active, children }: NavDisclosureProps) {
  const [open, setOpen] = React.useState(false)
  const wrapper = React.useRef<HTMLLIElement>(null)
  const button = React.useRef<HTMLButtonElement>(null)
  const panelId = React.useId()
  const close = React.useCallback(() => setOpen(false), [])

  React.useEffect(() => {
    if (!open) return
    const onPointer = (event: MouseEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        button.current?.focus()
      }
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <li
      ref={wrapper}
      className="relative"
      onMouseEnter={(event) => {
        if (event.nativeEvent instanceof MouseEvent && window.matchMedia('(hover: hover)').matches)
          setOpen(true)
      }}
      onMouseLeave={() => setOpen(false)}
      onBlur={(event) => {
        if (!wrapper.current?.contains(event.relatedTarget as Node | null)) setOpen(false)
      }}
    >
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          'inline-flex items-center gap-1 rounded-full px-3 py-2 text-sm font-semibold text-primary hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring',
          (open || active) && 'bg-secondary',
        )}
      >
        {label}
        <ChevronDown
          className={cn('size-4 transition-transform', open && 'rotate-180')}
          aria-hidden="true"
        />
      </button>
      <div
        id={panelId}
        hidden={!open}
        className={cn('absolute top-full left-0 z-50 pt-2', panelClassName)}
      >
        <div className="rounded-xl border bg-card p-5 shadow-raised">{children(close)}</div>
      </div>
    </li>
  )
}
