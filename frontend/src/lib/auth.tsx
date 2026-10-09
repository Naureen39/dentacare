import * as React from 'react'

import {
  apiGet,
  apiPost,
  mayHaveSession,
  onSessionExpired,
  refreshSession,
  tokenStore,
  type AuthenticatedResponse,
} from '@/lib/api-client'
import type { components } from '@/lib/api-types'

export type Me = components['schemas']['MeResponse']
export type Role = components['schemas']['UserRole']

/** What a sign in attempt led to. */
export type LoginOutcome =
  | { status: 'authenticated' }
  | { status: 'mfa_required'; mfaToken: string }
  | { status: 'mfa_setup_required'; mfaToken: string }

type LoginResponse =
  | AuthenticatedResponse
  | { status: 'mfa_required'; mfa_token: string }
  | { status: 'mfa_setup_required'; mfa_token: string }

export interface AuthState {
  status: 'loading' | 'authenticated' | 'anonymous'
  user: Me | null
}

export interface AuthApi extends AuthState {
  login: (email: string, password: string) => Promise<LoginOutcome>
  verifyMfa: (input: { mfaToken: string; code?: string; recoveryCode?: string }) => Promise<void>
  logout: () => Promise<void>
  /** Read the user again, after something about the account changed (such as two step sign in). */
  reloadUser: () => Promise<void>
}

const AuthContext = React.createContext<AuthApi | null>(null)

/** Where each kind of user lands after signing in. */
export const homeFor = (role: Role): string =>
  role === 'patient' ? '/portal' : role === 'admin' ? '/admin' : '/staff'

/**
 * Holds who is signed in. On load it tries to renew the session from the refresh cookie, so a
 * returning visitor is signed in again without seeing a form. The access token itself stays in
 * memory (see api-client).
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<AuthState>({ status: 'loading', user: null })

  const loadUser = React.useCallback(async () => {
    const user = await apiGet<Me>('/auth/me')
    setState({ status: 'authenticated', user })
  }, [])

  React.useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        // A first time visitor has no session cookie: skip the request that would only fail.
        const session = mayHaveSession() ? await refreshSession() : null
        if (cancelled) return
        if (!session) {
          setState({ status: 'anonymous', user: null })
          return
        }
        await loadUser()
      } catch {
        if (!cancelled) setState({ status: 'anonymous', user: null })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [loadUser])

  React.useEffect(() => onSessionExpired(() => setState({ status: 'anonymous', user: null })), [])

  const api = React.useMemo<AuthApi>(
    () => ({
      ...state,
      login: async (email, password) => {
        const response = await apiPost<LoginResponse>(
          '/auth/login',
          { email, password },
          { auth: false },
        )
        if (response.status === 'authenticated') {
          tokenStore.set(response.access_token)
          await loadUser()
          return { status: 'authenticated' }
        }
        return { status: response.status, mfaToken: response.mfa_token }
      },
      verifyMfa: async ({ mfaToken, code, recoveryCode }) => {
        const response = await apiPost<AuthenticatedResponse>(
          '/auth/mfa/verify',
          { mfa_token: mfaToken, code: code ?? null, recovery_code: recoveryCode ?? null },
          { auth: false },
        )
        tokenStore.set(response.access_token)
        await loadUser()
      },
      logout: async () => {
        try {
          await apiPost('/auth/logout')
        } finally {
          tokenStore.set(null)
          setState({ status: 'anonymous', user: null })
        }
      },
      reloadUser: loadUser,
    }),
    [state, loadUser],
  )

  return <AuthContext.Provider value={api}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthApi {
  const context = React.useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside an AuthProvider')
  return context
}
