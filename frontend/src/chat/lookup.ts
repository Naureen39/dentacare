import { useQuery } from '@tanstack/react-query'

import { apiGet } from '@/lib/api-client'
import type { components } from '@/lib/api-types'

export type PublicDentist = components['schemas']['DentistOut']

/** The dentists of the practice, for the cards the assistant offers. Asked for only when shown. */
export const useDentistCards = (enabled: boolean) =>
  useQuery({
    queryKey: ['public', 'all-dentists'],
    queryFn: () => apiGet<PublicDentist[]>('/public/dentists', { auth: false }),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  })
