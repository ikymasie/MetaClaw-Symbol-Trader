'use client';

import { useState, useEffect, useCallback } from 'react';
import { setupApi, accountsApi, type SetupStatus, type MT5Account } from '@/lib/api';

export type SetupStep = 'database' | 'accounts' | 'api-keys' | 'complete';

const STEPS: SetupStep[] = ['database', 'accounts', 'api-keys', 'complete'];

interface UseSetupReturn {
  /** Current setup status from the backend */
  status: SetupStatus | null;
  /** Whether we're loading status */
  loading: boolean;
  /** Active wizard step */
  step: SetupStep;
  /** Step index (0-based) */
  stepIndex: number;
  /** All MT5 accounts */
  accounts: MT5Account[];
  /** Global error message */
  error: string | null;
  /** Move to the next step */
  nextStep: () => void;
  /** Move to the previous step */
  prevStep: () => void;
  /** Jump to a specific step */
  goToStep: (step: SetupStep) => void;

  // Database
  testingDb: boolean;
  dbTestResult: { connected: boolean; message: string } | null;
  testDatabase: (url: string) => Promise<void>;
  saveDatabase: (url: string) => Promise<boolean>;

  // Accounts
  addingAccount: boolean;
  addAccount: (account: {
    label: string;
    mt5_login: number;
    mt5_password: string;
    mt5_server: string;
    is_default?: boolean;
  }) => Promise<boolean>;
  removeAccount: (id: string) => Promise<void>;
  testAccount: (id: string) => Promise<{ connected: boolean; message: string }>;
  refreshAccounts: () => Promise<void>;

  // API Keys
  savingKeys: boolean;
  saveApiKeys: (keys: {
    gemini_api_key?: string;
    gemini_model?: string;
    alpaca_news_api_key?: string;
  }) => Promise<boolean>;

  // Complete
  completing: boolean;
  completeSetup: () => Promise<boolean>;
  refreshStatus: () => Promise<void>;
}

export function useSetup(): UseSetupReturn {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState<SetupStep>('database');
  const [accounts, setAccounts] = useState<MT5Account[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Per-action loading states
  const [testingDb, setTestingDb] = useState(false);
  const [dbTestResult, setDbTestResult] = useState<{ connected: boolean; message: string } | null>(null);
  const [addingAccount, setAddingAccount] = useState(false);
  const [savingKeys, setSavingKeys] = useState(false);
  const [completing, setCompleting] = useState(false);

  const stepIndex = STEPS.indexOf(step);

  /** Fetch setup status from backend */
  const refreshStatus = useCallback(async (autoAdvance = false) => {
    try {
      const s = await setupApi.getStatus();
      setStatus(s);

      // Only auto-advance step on initial load, not after save operations
      if (autoAdvance) {
        if (!s.has_database) setStep('database');
        else if (!s.has_accounts) setStep('accounts');
        else if (!s.has_api_keys) setStep('api-keys');
        else setStep('complete');
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to check setup status';
      setError(msg);
    }
  }, []);

  /** Fetch accounts list */
  const refreshAccounts = useCallback(async () => {
    try {
      const res = await accountsApi.list();
      setAccounts(res.accounts);
    } catch {
      // Ignore — may not have accounts yet
    }
  }, []);

  // Initial load
  useEffect(() => {
    (async () => {
      setLoading(true);
      await refreshStatus(true);  // auto-advance on first load only
      await refreshAccounts();
      setLoading(false);
    })();
  }, [refreshStatus, refreshAccounts]);

  // Navigation
  const nextStep = useCallback(() => {
    const idx = STEPS.indexOf(step);
    if (idx < STEPS.length - 1) setStep(STEPS[idx + 1]);
  }, [step]);

  const prevStep = useCallback(() => {
    const idx = STEPS.indexOf(step);
    if (idx > 0) setStep(STEPS[idx - 1]);
  }, [step]);

  const goToStep = useCallback((s: SetupStep) => setStep(s), []);

  // ── Database ─────────────────────────────────────────────────────────

  const testDatabase = useCallback(async (url: string) => {
    setTestingDb(true);
    setDbTestResult(null);
    setError(null);
    try {
      const result = await setupApi.testDatabase(url);
      setDbTestResult(result);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Connection test failed';
      setDbTestResult({ connected: false, message: msg });
    } finally {
      setTestingDb(false);
    }
  }, []);

  const saveDatabase = useCallback(async (url: string): Promise<boolean> => {
    setError(null);
    try {
      await setupApi.saveDatabase(url);
      await refreshStatus();
      return true;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to save database URL';
      setError(msg);
      return false;
    }
  }, [refreshStatus]);

  // ── Accounts ─────────────────────────────────────────────────────────

  const addAccount = useCallback(async (account: {
    label: string;
    mt5_login: number;
    mt5_password: string;
    mt5_server: string;
    is_default?: boolean;
  }): Promise<boolean> => {
    setAddingAccount(true);
    setError(null);
    try {
      await accountsApi.add(account);
      await refreshAccounts();
      await refreshStatus();
      return true;
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e instanceof Error ? e.message : 'Failed to add account');
      setError(msg);
      return false;
    } finally {
      setAddingAccount(false);
    }
  }, [refreshAccounts, refreshStatus]);

  const removeAccount = useCallback(async (id: string) => {
    setError(null);
    try {
      await accountsApi.remove(id);
      await refreshAccounts();
      await refreshStatus();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to remove account';
      setError(msg);
    }
  }, [refreshAccounts, refreshStatus]);

  const testAccount = useCallback(async (id: string) => {
    try {
      return await accountsApi.test(id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Test failed';
      return { connected: false, message: msg };
    }
  }, []);

  // ── API Keys ─────────────────────────────────────────────────────────

  const saveApiKeys = useCallback(async (keys: {
    gemini_api_key?: string;
    gemini_model?: string;
    alpaca_news_api_key?: string;
  }): Promise<boolean> => {
    setSavingKeys(true);
    setError(null);
    try {
      await setupApi.saveApiKeys(keys);
      await refreshStatus();
      return true;
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e instanceof Error ? e.message : 'Failed to save API keys');
      setError(msg);
      return false;
    } finally {
      setSavingKeys(false);
    }
  }, [refreshStatus]);

  // ── Complete ─────────────────────────────────────────────────────────

  const completeSetup = useCallback(async (): Promise<boolean> => {
    setCompleting(true);
    setError(null);
    try {
      await setupApi.completeSetup();
      await refreshStatus();
      return true;
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e instanceof Error ? e.message : 'Setup completion failed');
      setError(msg);
      return false;
    } finally {
      setCompleting(false);
    }
  }, [refreshStatus]);

  return {
    status,
    loading,
    step,
    stepIndex,
    accounts,
    error,
    nextStep,
    prevStep,
    goToStep,
    testingDb,
    dbTestResult,
    testDatabase,
    saveDatabase,
    addingAccount,
    addAccount,
    removeAccount,
    testAccount,
    refreshAccounts,
    savingKeys,
    saveApiKeys,
    completing,
    completeSetup,
    refreshStatus,
  };
}
