import * as LabelPrimitive from '@radix-ui/react-label'
import * as React from 'react'

import { cn } from '@/lib/utils'

export const Label = React.forwardRef<
  React.ComponentRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root
    ref={ref}
    className={cn('text-sm leading-none font-medium text-foreground', className)}
    {...props}
  />
))
Label.displayName = 'Label'

export interface FieldProps {
  label: string
  /** Help text shown under the control. */
  hint?: string
  /** Error message. When set the control is marked invalid and the message is announced. */
  error?: string
  required?: boolean
  /** Use `inverted` on a dark background such as the footer. */
  tone?: 'default' | 'inverted'
  className?: string
  /** Receives the props that tie the control to its label, hint and error. */
  children: (control: {
    id: string
    'aria-describedby': string | undefined
    'aria-invalid': true | undefined
    'aria-required': true | undefined
  }) => React.ReactNode
}

/**
 * A label, a control, a hint and an error message wired together for assistive technology.
 * The control comes from a render function so it can be any input, select or custom widget.
 */
export function Field({
  label,
  hint,
  error,
  required,
  tone = 'default',
  className,
  children,
}: FieldProps) {
  const inverted = tone === 'inverted'
  const id = React.useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <Label htmlFor={id} className={cn(inverted && 'text-white')}>
        {label}
        {required && (
          <span className="ml-0.5 text-destructive" aria-hidden="true">
            *
          </span>
        )}
      </Label>
      {children({
        id,
        'aria-describedby': describedBy,
        'aria-invalid': error ? true : undefined,
        'aria-required': required ? true : undefined,
      })}
      {hint && (
        <p
          id={hintId}
          className={cn('text-sm', inverted ? 'text-white/90' : 'text-muted-foreground')}
        >
          {hint}
        </p>
      )}
      {error && (
        <p
          id={errorId}
          role="alert"
          className={cn('text-sm font-medium', inverted ? 'text-[#ffd6d6]' : 'text-destructive')}
        >
          {error}
        </p>
      )}
    </div>
  )
}
