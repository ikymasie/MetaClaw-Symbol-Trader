'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { tradingApi } from '@/lib/api';

/**
 * Status + history are now populated by useLiveFeed (WebSocket push).
 * The hooks below keep the same API surface so all components work unchanged —
 * they just read from the cache rather than polling via HTTP.
 *
 * refetchInterval is removed. The initial queryFn is kept so the cache
 * is seeded on first render (before the first WS message arrives).
 */

export function useTradingStatus() {
  return useQuery({
    queryKey: ['trading-status'],
    queryFn: tradingApi.getStatus,
    staleTime: Infinity,        // WS keeps it fresh — don't auto-refetch
    refetchOnWindowFocus: false,
  });
}

export function useTradingHistory() {
  return useQuery({
    queryKey: ['trading-history'],
    queryFn: tradingApi.getHistory,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function useVitalStatus() {
  return useQuery({
    queryKey: ['vital-status'],
    queryFn: tradingApi.getVitalStatus,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function useStartBot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (demoMode: boolean) => tradingApi.startSingleBot(demoMode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trading-status'] });
    },
  });
}

export function useStopBot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => tradingApi.stopSingleBot(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trading-status'] });
    },
  });
}

export function useUpdateConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (config: any) => tradingApi.updateConfig(config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trading-status'] });
      queryClient.invalidateQueries({ queryKey: ['ai-status'] });
    },
  });
}

export function useAIStatus() {
  return useQuery({
    queryKey: ['ai-status'],
    queryFn: tradingApi.getAIStatus,
    refetchInterval: 5000, // AI status not on WS — keep polling
  });
}

export function useAIDecisions() {
  return useQuery({
    queryKey: ['ai-decisions'],
    queryFn: () => tradingApi.getAIDecisions(50),
    refetchInterval: 10000,
  });
}

export function useTriggerAI() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => tradingApi.triggerAI(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-status'] });
    },
  });
}
