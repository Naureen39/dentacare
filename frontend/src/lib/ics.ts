import { clinic, fullAddress } from '@/content/site'

const stamp = (iso: string) =>
  new Date(iso)
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}/, '')

/** Escape text for an iCalendar value (RFC 5545 section 3.3.11). */
const escape = (text: string) =>
  text.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n')

export interface CalendarEvent {
  id: string
  start: string
  end: string
  service: string
  dentist: string
}

/** A calendar file for one appointment, built in the browser so guests can have one too. */
export function buildIcs(event: CalendarEvent): string {
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    `PRODID:-//${clinic.name}//Booking//EN`,
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:${event.id}@${new URL(clinic.siteUrl).hostname}`,
    `DTSTAMP:${stamp(new Date().toISOString())}`,
    `DTSTART:${stamp(event.start)}`,
    `DTEND:${stamp(event.end)}`,
    `SUMMARY:${escape(`${event.service} at ${clinic.name}`)}`,
    `DESCRIPTION:${escape(`With ${event.dentist}. Please arrive ten minutes early.`)}`,
    `LOCATION:${escape(`${clinic.name}, ${fullAddress}`)}`,
    'BEGIN:VALARM',
    'TRIGGER:-PT24H',
    'ACTION:DISPLAY',
    `DESCRIPTION:${escape(`Dental appointment tomorrow: ${event.service}`)}`,
    'END:VALARM',
    'END:VEVENT',
    'END:VCALENDAR',
  ]
  return lines.join('\r\n') + '\r\n'
}
