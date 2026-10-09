import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach, expect, vi } from 'vitest'
import * as matchers from 'vitest-axe/matchers'

// Pages load as separate chunks, which takes longer the first time under a full run.
configure({ asyncUtilTimeout: 8_000 })

expect.extend(matchers)

// jsdom has no layout engine, so the browser features the components lean on are stubbed.
class NoopObserver {
  observe(...args: [Element]): void {
    void args
  }
  unobserve(...args: [Element]): void {
    void args
  }
  disconnect() {}
  takeRecords() {
    return []
  }
}
// Plain assignment, not vi.stubGlobal, so tests that call vi.unstubAllGlobals keep them.
globalThis.ResizeObserver = NoopObserver as unknown as typeof ResizeObserver
// Reports every watched element as visible straight away, so scroll animations run in tests.
class VisibleObserver extends NoopObserver {
  constructor(private callback: IntersectionObserverCallback) {
    super()
  }
  override observe(target: Element) {
    this.callback([{ isIntersecting: true, target } as IntersectionObserverEntry], this as never)
  }
}
globalThis.IntersectionObserver = VisibleObserver as unknown as typeof IntersectionObserver

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches:
      query.includes('prefers-reduced-motion') &&
      (globalThis as { __reduceMotion?: boolean }).__reduceMotion === true,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }),
})

window.scrollTo = vi.fn()
Element.prototype.scrollIntoView = vi.fn()
// Radix selects and popovers use pointer capture, which jsdom does not implement.
Element.prototype.hasPointerCapture = () => false
Element.prototype.setPointerCapture = () => {}
Element.prototype.releasePointerCapture = () => {}

afterEach(() => {
  cleanup()
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
})
