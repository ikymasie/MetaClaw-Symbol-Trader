import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  tradingApi, 
  accountsApi, 
  type BotDeployRequest, 
  type FleetConfig, 
  type BotSnapshot, 
  type FleetStatus,
  type MT5Account,
  type MT5Symbol,
  type AvailableSymbol,
  type WizardGenerateRequest,
  type WizardResult
} from '@/lib/api';

export type { 
  BotDeployRequest, 
  FleetConfig, 
  BotSnapshot, 
  FleetStatus,
  MT5Account,
  MT5Symbol,
  AvailableSymbol,
  WizardGenerateRequest,
  WizardResult
};


export const FLEET_KEY = 'fleet-status';
export const FLEET_CONFIG_KEY = 'fleet-config';

/** Poll fleet status every 3 seconds */
export function useFleetStatus() {
  return useQuery({
    queryKey: [FLEET_KEY],
    queryFn: tradingApi.getFleetStatus,
    refetchInterval: 3000,
    retry: 2,
  });
}

/** Fleet config — static, refetch on demand */
export function useFleetConfig() {
  return useQuery({
    queryKey: [FLEET_CONFIG_KEY],
    queryFn: tradingApi.getFleetConfig,
    staleTime: 10_000,
  });
}

/** Deploy a new bot */
export function useDeployBot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (config: BotDeployRequest | Record<string, any>) =>
      tradingApi.deployBot(config as BotDeployRequest),
    onSuccess: () => qc.invalidateQueries({ queryKey: [FLEET_KEY] }),
  });
}

/** Kill a bot */
export function useKillBot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) => tradingApi.killBot(botId),
    onSuccess: () => qc.invalidateQueries({ queryKey: [FLEET_KEY] }),
  });
}

/** Start a bot's engine */
export function useStartBotEngine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) => tradingApi.startBot(botId),
    onSuccess: () => qc.invalidateQueries({ queryKey: [FLEET_KEY] }),
  });
}

/** Stop a bot's engine */
export function useStopBotEngine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) => tradingApi.stopBotEngine(botId),
    onSuccess: () => qc.invalidateQueries({ queryKey: [FLEET_KEY] }),
  });
}

/** Trigger AI Brain for a specific bot */
export function useTriggerBotAI() {
  return useMutation({
    mutationFn: (botId: string) => tradingApi.triggerBotAI(botId),
  });
}

/** Update fleet config */
export function useUpdateFleetConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (updates: Partial<FleetConfig>) => tradingApi.updateFleetConfig(updates),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [FLEET_CONFIG_KEY] });
      qc.invalidateQueries({ queryKey: [FLEET_KEY] });
    },
  });
}

/** Update a single bot's config (e.g. qty, stop_loss_pct) */
export function useUpdateBotConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ botId, updates }: { botId: string; updates: Record<string, unknown> }) =>
      tradingApi.updateBotConfig(botId, updates),
    onMutate: async ({ botId, updates }) => {
      // Cancel in-flight fleet refetches so they don't overwrite our optimistic update
      await qc.cancelQueries({ queryKey: [FLEET_KEY] });

      // Snapshot previous value for rollback
      const previous = qc.getQueryData<FleetStatus>([FLEET_KEY]);

      // Optimistically patch the cached fleet data
      if (previous) {
        qc.setQueryData<FleetStatus>([FLEET_KEY], {
          ...previous,
          bots: previous.bots.map((b) =>
            b.bot_id === botId ? { ...b, ...updates } : b
          ),
        });
      }

      return { previous };
    },
    onError: (_err, _vars, context) => {
      // Roll back to the previous fleet data on failure
      if (context?.previous) {
        qc.setQueryData([FLEET_KEY], context.previous);
      }
    },
    onSettled: () => {
      // Always refetch after mutation to ensure server state is authoritative
      qc.invalidateQueries({ queryKey: [FLEET_KEY] });
    },
  });
}

/**
 * Derives a single BotSnapshot from the cached fleet response — no extra HTTP call.
 * Returns undefined while the fleet hasn't loaded yet.
 */
export function useFleetBotDetail(botId: string | null): BotSnapshot | undefined {
  const qc = useQueryClient();
  const fleet = qc.getQueryData<FleetStatus>([FLEET_KEY]);
  return fleet?.bots?.find((b) => b.bot_id === botId);
}

/** Per-bot AI status — polls every 5 s */
export function useBotAIStatus(botId: string | null) {
  return useQuery({
    queryKey: ['bot-ai-status', botId],
    queryFn: () => tradingApi.getFleetBotAIStatus(botId!),
    enabled: !!botId,
    refetchInterval: 5000,
  });
}

/** Per-bot AI decision log */
export function useBotAIDecisions(botId: string | null) {
  return useQuery({
    queryKey: ['bot-ai-decisions', botId],
    queryFn: () => tradingApi.getFleetBotAIDecisions(botId!),
    enabled: !!botId,
    refetchInterval: 10000,
  });
}

/** MT5 Account Info — polls every 10 s when connected, backs off to 30 s when disconnected */
export function useMT5Account() {
  return useQuery({
    queryKey: ['mt5-account'],
    queryFn: tradingApi.getAccountInfo,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && data.status === 'DISCONNECTED') {
        return 30_000; // Back off when MT5 isn't reachable
      }
      return 10_000;
    },
    retry: 1,
  });
}

/** Fetch market data for a specific symbol.
 *  Polls every 5 s when data is available, backs off to 60 s when market is closed
 *  so we don't spam the backend with requests that will just return empty arrays. */
export function useMarketData(symbol: string) {
  const query = useQuery({
    queryKey: ['market-data', symbol],
    queryFn: () => tradingApi.getMarketData(symbol),
    refetchInterval: (query) => {
      const data = query.state.data;
      // If the response has no price data (market closed), back off to 60 s
      if (data && (!data.price_data || data.price_data.length === 0)) {
        return 60_000;
      }
      return 5_000;
    },
    enabled: !!symbol,
    retry: 1,               // Don't hammer retries on failure
    retryDelay: 10_000,     // Wait 10 s before retry
  });
  return query;
}

/** Fetch available symbols from MT5 terminal */
export function useAvailableSymbols() {
  return useQuery({
    queryKey: ['available-symbols'],
    queryFn: tradingApi.getAvailableSymbols,
    staleTime: 60_000, // 1 minute
  });
}

/** Fetch all configured MT5 accounts */
export function useAccounts() {
  return useQuery({
    queryKey: ['accounts'],
    queryFn: accountsApi.list,
    staleTime: 30_000,
  });
}

/** Fetch symbols for a specific account */
export function useAccountSymbols(accountId: string | null) {
  return useQuery({
    queryKey: ['account-symbols', accountId],
    queryFn: () => accountsApi.getSymbols(accountId!),
    enabled: !!accountId,
    staleTime: 60_000,
  });
}

/** Generate a bot config via AI */
export function useGenerateBot() {
  return useMutation({
    mutationFn: (req: WizardGenerateRequest) => tradingApi.wizardGenerate(req),
  });
}

