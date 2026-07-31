/** React Query hooks. Centralized keys + polling cadence for "live" feel. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type { SettingsPatch } from './types'

/** Public data refreshes on a calm cadence — live, not frantic. */
const SNAPSHOT_REFETCH_MS = 30_000
const STATUS_REFETCH_MS = 15_000

/** The book/activity update as the engine ticks — poll a touch faster. */
const BOOK_REFETCH_MS = 10_000

export const queryKeys = {
  status: ['status'] as const,
  snapshot: (top: number) => ['snapshot', top] as const,
  book: ['book'] as const,
  usBook: ['us-book'] as const,
  performance: ['performance'] as const,
  activity: ['activity'] as const,
}

export function usePerformance() {
  return useQuery({
    queryKey: queryKeys.performance,
    queryFn: api.performance,
    refetchInterval: BOOK_REFETCH_MS,
  })
}

export function useBook() {
  return useQuery({
    queryKey: queryKeys.book,
    queryFn: api.book,
    refetchInterval: BOOK_REFETCH_MS,
  })
}

export function useUsBook() {
  return useQuery({
    queryKey: queryKeys.usBook,
    queryFn: api.usBook,
    refetchInterval: BOOK_REFETCH_MS,
  })
}

export function useActivity(limit = 100) {
  return useQuery({
    queryKey: queryKeys.activity,
    queryFn: () => api.activity(limit),
    refetchInterval: BOOK_REFETCH_MS,
  })
}

export function useSettings() {
  return useQuery({ queryKey: ['settings'], queryFn: api.settings })
}

function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ['settings'] })
  qc.invalidateQueries({ queryKey: ['follows'] })
  qc.invalidateQueries({ queryKey: queryKeys.status })
  qc.invalidateQueries({ queryKey: queryKeys.book })
  qc.invalidateQueries({ queryKey: queryKeys.performance })
  qc.invalidateQueries({ queryKey: queryKeys.activity })
}

/** Mutation that saves risk settings and refreshes the surfaces they affect. */
export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: SettingsPatch) => api.updateSettings(patch),
    onSuccess: () => invalidateAll(qc),
  })
}

/** Wipe follows, book and history (keeps config). */
export function useResetBook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.resetBook(),
    onSuccess: () => invalidateAll(qc),
  })
}

export function useStatus() {
  return useQuery({
    queryKey: queryKeys.status,
    queryFn: api.status,
    refetchInterval: STATUS_REFETCH_MS,
    staleTime: STATUS_REFETCH_MS,
  })
}

export function useSnapshot(top = 10) {
  return useQuery({
    queryKey: queryKeys.snapshot(top),
    queryFn: () => api.snapshot(top),
    refetchInterval: SNAPSHOT_REFETCH_MS,
    staleTime: SNAPSHOT_REFETCH_MS,
    refetchOnWindowFocus: true,
  })
}
