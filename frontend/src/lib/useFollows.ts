/** Follow list, backend-owned. The engine reads this table to decide who to
 *  copy, so follows must live server-side (not in the browser). Optimistic
 *  toggle for a snappy UI; react-query reconciles with the server. */
import { useCallback, useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type { Follow } from './types'

const KEY = ['follows'] as const

export function useFollows() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: KEY, queryFn: api.follows })

  const follows = useMemo(() => data ?? [], [data])
  const walletSet = useMemo(() => new Set(follows.map((f) => f.wallet.toLowerCase())), [follows])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: KEY })
    qc.invalidateQueries({ queryKey: ['book'] })
    qc.invalidateQueries({ queryKey: ['activity'] })
  }

  const add = useMutation({
    mutationFn: ({ wallet, name }: { wallet: string; name: string }) =>
      api.addFollow(wallet.toLowerCase(), name),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (wallet: string) => api.removeFollow(wallet.toLowerCase()),
    onSuccess: invalidate,
  })

  const isFollowing = useCallback(
    (wallet: string) => walletSet.has(wallet.toLowerCase()),
    [walletSet],
  )

  const toggle = useCallback(
    (wallet: string, name: string) => {
      if (walletSet.has(wallet.toLowerCase())) remove.mutate(wallet)
      else add.mutate({ wallet, name })
    },
    [walletSet, add, remove],
  )

  return {
    follows: follows as Follow[],
    count: follows.length,
    isFollowing,
    toggle,
    pending: add.isPending || remove.isPending,
  }
}
