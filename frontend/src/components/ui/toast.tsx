import * as ToastPrimitive from '@radix-ui/react-toast'
import { AlertTriangle, CheckCircle2, Info, X, XCircle, type LucideIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

type Tone = 'success' | 'error' | 'warning' | 'info'

interface ToastItem {
  id: number
  tone: Tone
  title: string
  description?: string
}

interface ToastApi {
  toast: (item: Omit<ToastItem, 'id' | 'tone'> & { tone?: Tone }) => void
}

const ToastContext = React.createContext<ToastApi | null>(null)

const icons: Record<Tone, LucideIcon> = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
}
const accents: Record<Tone, string> = {
  success: 'border-l-success-strong text-success-strong',
  error: 'border-l-destructive text-destructive',
  warning: 'border-l-warning-strong text-warning-strong',
  info: 'border-l-accent-strong text-accent-strong',
}

/** Wrap the application once. Errors are announced assertively, everything else politely. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([])
  const counter = React.useRef(0)

  const api = React.useMemo<ToastApi>(
    () => ({
      toast: ({ tone = 'info', ...rest }) => {
        counter.current += 1
        setItems((current) => [...current.slice(-3), { id: counter.current, tone, ...rest }])
      },
    }),
    [],
  )

  return (
    <ToastContext.Provider value={api}>
      <ToastPrimitive.Provider swipeDirection="right" duration={6000} label="Notifications">
        {children}
        {items.map((item) => {
          const Icon = icons[item.tone]
          return (
            <ToastPrimitive.Root
              key={item.id}
              type={item.tone === 'error' ? 'foreground' : 'background'}
              onOpenChange={(open) => {
                if (!open) setItems((current) => current.filter((t) => t.id !== item.id))
              }}
              className={cn(
                'relative flex items-start gap-3 rounded-lg border border-l-4 bg-card p-4 pr-10 shadow-raised data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:slide-in-from-right-4',
                accents[item.tone],
              )}
            >
              <Icon className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
              <div className="flex flex-col gap-1">
                <ToastPrimitive.Title className="text-sm font-semibold text-foreground">
                  {item.title}
                </ToastPrimitive.Title>
                {item.description && (
                  <ToastPrimitive.Description className="text-sm text-muted-foreground">
                    {item.description}
                  </ToastPrimitive.Description>
                )}
              </div>
              <ToastPrimitive.Close
                aria-label="Dismiss notification"
                className="absolute top-2 right-2 inline-flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
              >
                <X className="size-4" aria-hidden="true" />
              </ToastPrimitive.Close>
            </ToastPrimitive.Root>
          )
        })}
        <ToastPrimitive.Viewport className="fixed right-0 bottom-0 z-[100] m-0 flex w-full max-w-sm list-none flex-col gap-3 p-4 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const context = React.useContext(ToastContext)
  if (!context) throw new Error('useToast must be used inside a ToastProvider')
  return context
}
