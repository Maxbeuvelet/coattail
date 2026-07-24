/** Owner state for public/shared deployments.
 *
 * The backend enforces the real gate (mutating endpoints require the key); this
 * hook just tells the UI whether to SHOW controls, and lets the owner unlock a
 * device. When no OWNER_KEY is configured (local dev), everyone is the owner.
 */
import { useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, setOwnerKey } from './api'

/** Capture `?key=…` from the URL once at startup, persist it, and clean the URL
 *  so the secret isn't left sitting in the address bar. Call before render. */
export function captureOwnerKeyFromUrl(): void {
  try {
    const params = new URLSearchParams(window.location.search)
    const key = params.get('key')
    if (key) {
      setOwnerKey(key)
      params.delete('key')
      const qs = params.toString()
      window.history.replaceState(
        {},
        '',
        window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash,
      )
    }
  } catch {
    /* no-op */
  }
}

export function useOwner() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['whoami'],
    queryFn: api.whoami,
    staleTime: Infinity,
  })

  const unlock = useCallback(
    (key: string) => {
      setOwnerKey(key.trim())
      qc.invalidateQueries({ queryKey: ['whoami'] })
    },
    [qc],
  )
  const lock = useCallback(() => {
    setOwnerKey(null)
    qc.invalidateQueries({ queryKey: ['whoami'] })
  }, [qc])

  return {
    // Default to read-only until we know, so controls never flash on a public view.
    isOwner: data?.owner ?? false,
    authRequired: data?.authRequired ?? false,
    isLoading,
    unlock,
    lock,
  }
}
