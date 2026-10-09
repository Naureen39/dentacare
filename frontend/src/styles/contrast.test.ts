import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { AA_LARGE, AA_TEXT, contrastRatio } from '@/lib/contrast'

const css = readFileSync(path.resolve(import.meta.dirname, 'globals.css'), 'utf-8')

/** The custom properties declared in :root. */
function tokens(): Record<string, string> {
  const root = /:root\s*\{([\s\S]*?)\n\}/.exec(css)?.[1] ?? ''
  const out: Record<string, string> = {}
  for (const [, name, value] of root.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    out[name as string] = (value as string).toLowerCase()
  }
  return out
}

const t = tokens()

// Foreground token, background token, the minimum ratio and where the pair is used.
const textPairs: [string, string, number, string][] = [
  ['foreground', 'background', AA_TEXT, 'body text on the page'],
  ['foreground', 'card', AA_TEXT, 'body text on cards'],
  ['muted-foreground', 'background', AA_TEXT, 'secondary text on the page'],
  ['muted-foreground', 'card', AA_TEXT, 'secondary text on cards'],
  ['muted-foreground', 'secondary', AA_TEXT, 'secondary text on mint'],
  ['muted-foreground', 'muted', AA_TEXT, 'secondary text on grey surfaces'],
  ['primary', 'background', AA_TEXT, 'headings'],
  ['primary', 'secondary', AA_TEXT, 'text on mint, ghost button hover'],
  ['primary', 'muted', AA_TEXT, 'text on grey surfaces'],
  ['primary-foreground', 'primary', AA_TEXT, 'primary button, footer'],
  ['accent-strong-foreground', 'accent-strong', AA_TEXT, 'accent button'],
  ['accent-strong', 'background', AA_TEXT, 'links and active text'],
  ['accent-strong', 'card', AA_TEXT, 'links on cards'],
  ['accent-strong', 'secondary', AA_TEXT, 'links on mint'],
  ['success-strong', 'success-soft', AA_TEXT, 'success badge'],
  ['success-strong', 'card', AA_TEXT, 'success text on cards'],
  ['warning-strong', 'warning-soft', AA_TEXT, 'warning badge'],
  ['warning-strong', 'card', AA_TEXT, 'warning text on cards'],
  ['destructive', 'destructive-soft', AA_TEXT, 'error banner and danger badge'],
  ['destructive', 'card', AA_TEXT, 'error text on cards'],
  ['destructive', 'background', AA_TEXT, 'error text on the page'],
]

describe('colour tokens meet WCAG 2.2 AA', () => {
  it('has every token the pairs rely on', () => {
    for (const [fg, bg] of textPairs) {
      expect(t[fg], fg).toBeDefined()
      expect(t[bg], bg).toBeDefined()
    }
  })

  it.each(textPairs)('%s on %s needs %s:1 (%s)', (fg, bg, minimum) => {
    const ratio = contrastRatio(t[fg] as string, t[bg] as string)
    expect(ratio).toBeGreaterThanOrEqual(minimum)
  })

  it('white text on the destructive button is readable', () => {
    expect(contrastRatio('#ffffff', t.destructive as string)).toBeGreaterThanOrEqual(AA_TEXT)
  })

  it('form control edges and focus rings are visible (3:1 for interface parts)', () => {
    expect(contrastRatio(t.input as string, t.card as string)).toBeGreaterThanOrEqual(AA_LARGE)
    expect(contrastRatio(t.ring as string, t.background as string)).toBeGreaterThanOrEqual(AA_LARGE)
    expect(contrastRatio(t.ring as string, t.card as string)).toBeGreaterThanOrEqual(AA_LARGE)
  })

  it('keeps the brand colours from the design brief', () => {
    expect(t.primary).toBe('#0b2545')
    expect(t.accent).toBe('#13a3a1')
    expect(t.secondary).toBe('#e8f6f5')
    expect(t.background).toBe('#fafbfc')
    expect(t.success).toBe('#1e9e6a')
    expect(t.warning).toBe('#e39b1d')
    expect(t.danger).toBe('#d64545')
  })

  it('does not put the brand teal, green, amber or red under normal text', () => {
    // These fail 4.5:1 on white, which is why the strong variants exist. They remain allowed for
    // fills, icons and large display text (3:1).
    for (const brand of ['accent', 'success', 'warning', 'danger']) {
      expect(contrastRatio(t[brand] as string, '#ffffff'), brand).toBeLessThan(AA_TEXT)
    }
    expect(contrastRatio(t.accent as string, t.primary as string)).toBeGreaterThanOrEqual(AA_LARGE)
  })
})

describe('contrast calculation', () => {
  it('matches known values', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 1)
    expect(contrastRatio('#ffffff', '#ffffff')).toBeCloseTo(1, 5)
    expect(contrastRatio('#767676', '#ffffff')).toBeCloseTo(4.54, 1)
  })
})

describe('type and layout settings', () => {
  it('self hosts the fonts and respects reduced motion', () => {
    expect(css).toContain('@fontsource-variable/inter')
    expect(css).toContain('@fontsource-variable/plus-jakarta-sans')
    expect(css).not.toMatch(/fonts\.googleapis|fonts\.gstatic/)
    expect(css).toContain('prefers-reduced-motion: reduce')
  })

  it('uses a 1240px content width and the 56 / 96px section spacing', () => {
    expect(css).toContain('--max-width-page: 1240px')
    expect(css).toMatch(/padding-block: 3\.5rem/)
    expect(css).toMatch(/padding-block: 6rem/)
  })
})
