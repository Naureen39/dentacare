import { animate, useInView, useReducedMotion } from 'motion/react'
import * as React from 'react'

/**
 * Fades content up by at most 24px over 400ms as it scrolls into view, once. The content is
 * always in the page as it is first rendered, so it shows before any script runs; only content
 * that starts below the visible area is hidden and then revealed. With the visitor's "reduce
 * motion" setting on, the content is simply shown.
 */
export function FadeUp({
  children,
  delay = 0,
  className,
  as = 'div',
}: {
  children: React.ReactNode
  delay?: number
  className?: string
  as?: 'div' | 'section' | 'li' | 'article'
}) {
  const reduced = useReducedMotion()
  const ref = React.useRef<HTMLElement>(null)
  React.useEffect(() => {
    const element = ref.current
    if (reduced || !element || element.getBoundingClientRect().top < window.innerHeight * 0.9)
      return
    element.style.opacity = '0'
    element.style.transform = 'translateY(24px)'
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return
        observer.disconnect()
        void animate(
          element,
          { opacity: 1, transform: 'translateY(0px)' },
          { duration: 0.4, delay, ease: 'easeOut' },
        ).then(() => {
          element.style.opacity = ''
          element.style.transform = ''
        })
      },
      { rootMargin: '0px 0px -10% 0px' },
    )
    observer.observe(element)
    return () => {
      observer.disconnect()
      element.style.opacity = ''
      element.style.transform = ''
    }
  }, [reduced, delay])
  return React.createElement(as, { className, ref }, children)
}

export interface AnimatedNumberProps {
  value: number
  /** Formats the number, for example as dollars or a percentage. */
  format?: (value: number) => string
  durationMs?: number
  className?: string
}

const plain = (value: number) =>
  new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value)

/**
 * Counts up to a value when it first scrolls into view. Assistive technology always reads the
 * final value, never the numbers in between, and motion is skipped when reduced.
 */
export function AnimatedNumber({
  value,
  format = plain,
  durationMs = 900,
  className,
}: AnimatedNumberProps) {
  const reduced = useReducedMotion()
  const ref = React.useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true })
  const [shown, setShown] = React.useState(value)

  React.useEffect(() => {
    if (reduced || !inView) return
    const controls = animate(0, value, {
      duration: durationMs / 1000,
      ease: 'easeOut',
      onUpdate: setShown,
    })
    return () => controls.stop()
  }, [inView, reduced, value, durationMs])

  return (
    <span ref={ref} className={className}>
      <span className="sr-only">{format(value)}</span>
      <span aria-hidden="true">{format(reduced ? value : shown)}</span>
    </span>
  )
}
