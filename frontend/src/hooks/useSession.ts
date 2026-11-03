'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { sessionApi, type SessionStatus, type AvailableSymbol } from '@/lib/api';

export function useSessionStatus() {
  return useQuery<SessionStatus>({
    queryKey: ['session-status'],
    queryFn: () => sessionApi.getStatus(),
    refetchInterval: 3000,
  });
}

export function useSessionStart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: { symbol: string; spirit: string; capital_allocation?: number; qty?: number }) =>
      sessionApi.start(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['session-status'] });
    },
  });
}

export function useSessionStop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => sessionApi.stop(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['session-status'] });
    },
  });
}

export function useSessionHistory() {
  return useQuery({
    queryKey: ['session-history'],
    queryFn: () => sessionApi.getHistory(200),
    refetchInterval: 10000,
  });
}

export function useSessionDeliberation() {
  return useQuery({
    queryKey: ['session-deliberation'],
    queryFn: () => sessionApi.getDeliberation(),
    refetchInterval: 5000,
  });
}

export function useSessionAgents() {
  return useQuery({
    queryKey: ['session-agents'],
    queryFn: () => sessionApi.getAgentsStatus(),
    refetchInterval: 5000,
  });
}

export function useAvailableSymbols() {
  return useQuery<{ symbols: AvailableSymbol[] }>({
    queryKey: ['available-symbols'],
    queryFn: () => sessionApi.getAvailableSymbols(),
    staleTime: 60000,
  });
}

export function useMT5AccountInfo() {
  return useQuery({
    queryKey: ['mt5-account'],
    queryFn: () => sessionApi.getAccountInfo(),
    refetchInterval: 10000,
  });
}

export function useMarketData(symbol: string) {
  return useQuery({
    queryKey: ['market-data', symbol],
    queryFn: () => sessionApi.getMarketData(symbol),
    refetchInterval: 5000,
    enabled: !!symbol,
  });
}
