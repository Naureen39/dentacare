import { describe, expect, it } from 'vitest'

import {
  addDays,
  addMonths,
  dateInZone,
  daysInMonth,
  formatDate,
  formatTime,
  monthGrid,
  parseDate,
  startOfMonth,
  toDateString,
  weekday,
} from '@/lib/dates'

describe('calendar dates', () => {
  it('round trips between strings and dates without a time zone shift', () => {
    expect(toDateString(parseDate('2026-03-08'))).toBe('2026-03-08') // daylight saving starts that day
    expect(toDateString(parseDate('2026-11-01'))).toBe('2026-11-01') // and ends on this one
  })

  it('adds days across month, year and daylight saving boundaries', () => {
    expect(addDays('2026-01-31', 1)).toBe('2026-02-01')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addDays('2026-03-07', 2)).toBe('2026-03-09')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
  })

  it('adds months and keeps the day inside the shorter month', () => {
    expect(addMonths('2026-01-31', 1)).toBe('2026-02-28')
    expect(addMonths('2028-01-31', 1)).toBe('2028-02-29')
    expect(addMonths('2026-11-15', 3)).toBe('2027-02-15')
    expect(addMonths('2026-01-15', -2)).toBe('2025-11-15')
  })

  it('knows month lengths and weekdays', () => {
    expect(daysInMonth('2026-02-10')).toBe(28)
    expect(daysInMonth('2028-02-10')).toBe(29)
    expect(startOfMonth('2026-07-19')).toBe('2026-07-01')
    expect(weekday('2026-10-08')).toBe(4) // a Thursday
  })

  it('formats in words', () => {
    expect(formatDate('2026-10-08')).toBe('Thursday, October 8, 2026')
    expect(formatDate('2026-10-08', { month: 'short', day: 'numeric' })).toBe('Oct 8')
  })

  it('shows times and days in the clinic time zone, whatever the visitor has', () => {
    const iso = '2026-07-01T03:30:00Z' // 11:30 PM on 30 June in New York
    expect(formatTime(iso, 'America/New_York')).toBe('11:30 PM')
    expect(dateInZone(iso, 'America/New_York')).toBe('2026-06-30')
    expect(dateInZone(iso, 'Asia/Tokyo')).toBe('2026-07-01')
  })

  it('lays out a month in weeks', () => {
    const sundayFirst = monthGrid('2026-10-01')
    expect(sundayFirst.every((week) => week.length === 7)).toBe(true)
    expect(sundayFirst[0]?.[4]).toBe('2026-10-01') // 1 October 2026 is a Thursday
    expect(sundayFirst.flat().filter(Boolean)).toHaveLength(31)
    expect(monthGrid('2026-10-01', 1)[0]?.[3]).toBe('2026-10-01')
    expect(monthGrid('2026-02-01').flat().filter(Boolean)).toHaveLength(28)
  })
})
