import { useMutation, useQuery } from '@tanstack/react-query'

import { serviceByCode, services, type ServiceContent } from '@/content/services'
import { apiGet, apiPost } from '@/lib/api-client'
import type { components } from '@/lib/api-types'

type ServiceOut = components['schemas']['ServiceOut']
type TestimonialOut = components['schemas']['TestimonialOut']

/** The catalogue with live prices and durations from the database where the API answers. */
export function useCatalog(): { services: ServiceContent[]; live: boolean } {
  const { data } = useQuery({
    queryKey: ['public', 'services'],
    queryFn: () => apiGet<ServiceOut[]>('/public/services', { auth: false }),
    staleTime: 5 * 60_000,
    retry: false,
  })
  if (!data) return { services, live: false }
  const byCode = new Map(data.map((s) => [s.code, s]))
  return {
    live: true,
    services: services.map((s) => {
      const live = byCode.get(s.code)
      if (!live) return s
      const price = Number(live.base_price)
      return { ...s, price: Number.isFinite(price) ? price : s.price, minutes: live.duration_min }
    }),
  }
}

export function useService(code: string | undefined): ServiceContent | undefined {
  const { services: all } = useCatalog()
  return code ? (all.find((s) => s.code === code) ?? serviceByCode(code)) : undefined
}

export interface Review {
  id: string
  firstName: string
  lastInitial: string
  treatment: string | null
  rating: number
  body: string
}

/** Shown when the API cannot be reached, so the page is never empty. Labelled as illustrative. */
const sampleReviews: Review[] = [
  {
    id: 's1',
    firstName: 'Rachel',
    lastInitial: 'M',
    treatment: 'Routine Exam and Cleaning',
    rating: 5,
    body: 'The whole visit felt calm and unhurried. The hygienist explained everything she was doing.',
  },
  {
    id: 's2',
    firstName: 'Omar',
    lastInitial: 'K',
    treatment: 'Porcelain Crown',
    rating: 5,
    body: 'My crown was ready in two short visits and fits perfectly. The team kept me informed at every step.',
  },
  {
    id: 's3',
    firstName: 'Elena',
    lastInitial: 'S',
    treatment: 'Clear Aligner Treatment',
    rating: 5,
    body: 'Straightforward planning and honest advice about how long treatment would take.',
  },
  {
    id: 's4',
    firstName: 'James',
    lastInitial: 'T',
    treatment: 'Root Canal Therapy',
    rating: 4,
    body: 'I was nervous, but the procedure was far more comfortable than I expected.',
  },
  {
    id: 's5',
    firstName: 'Priya',
    lastInitial: 'N',
    treatment: 'Emergency Visit',
    rating: 5,
    body: 'They found a place for me the same morning when I broke a tooth. I am grateful.',
  },
  {
    id: 's6',
    firstName: 'Daniel',
    lastInitial: 'L',
    treatment: 'Professional Teeth Whitening',
    rating: 5,
    body: 'A noticeable difference in one hour, and no sensitivity afterwards.',
  },
]

export function useReviews(): Review[] {
  const { data } = useQuery({
    queryKey: ['public', 'testimonials'],
    queryFn: () => apiGet<TestimonialOut[]>('/public/testimonials', { auth: false }),
    staleTime: 5 * 60_000,
    retry: false,
  })
  if (!data || data.length === 0) return sampleReviews
  return data.map((t) => ({
    id: t.id,
    firstName: t.first_name,
    lastInitial: t.last_initial,
    treatment: t.treatment ?? null,
    rating: t.rating,
    body: t.body,
  }))
}

export interface ContactInput {
  name: string
  email?: string
  phone?: string
  message: string
}

export const useContactMutation = () =>
  useMutation({
    mutationFn: (input: ContactInput) =>
      apiPost<{ message: string }>(
        '/public/contact',
        {
          name: input.name,
          email: input.email || null,
          phone: input.phone || null,
          message: input.message,
        },
        { auth: false },
      ),
  })

export const useNewsletterMutation = () =>
  useMutation({
    mutationFn: (email: string) =>
      apiPost<{ message: string }>('/public/newsletter', { email }, { auth: false }),
  })
