import type { Page, Route } from '@playwright/test';
import {
  mockFleetStatus,
  mockFleetConfig,
  mockMT5Account,
  mockMarketData,
  mockSetupStatus,
  mockMT5Accounts,
  mockDbTestSuccess,
  mockAvailableSymbols,
  mockAccountSymbols,
  mockSystemResources,
  mockDeployResult,
  mockWizardResult,
} from './fixtures';

/**
 * Sets up all API route mocks for the TradeClaw frontend.
 * Call in `test.beforeEach` to mock every backend endpoint.
 */
export async function setupApiMocks(page: Page) {
  // Intercept all backend API calls (localhost:8000)
  await page.route('http://localhost:8000/**', async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const path = url.pathname;

    // ── Fleet ────────────────────────────────────────────
    if (method === 'GET' && path === '/fleet/status') {
      return json(route, mockFleetStatus(5));
    }
    if (method === 'GET' && path === '/fleet/config') {
      return json(route, mockFleetConfig);
    }
    if (method === 'POST' && path === '/fleet/deploy') {
      return json(route, mockDeployResult);
    }
    if (method === 'POST' && path === '/fleet/config') {
      return json(route, { ok: true });
    }

    // Bot CRUD
    const botMatch = path.match(/^\/fleet\/bot\/([^/]+)$/);
    if (botMatch && method === 'GET') {
      return json(route, { bot_id: botMatch[1], status: { bot_status: 'RUNNING' } });
    }
    if (botMatch && method === 'DELETE') {
      return json(route, { ok: true, bot_id: botMatch[1] });
    }
    if (botMatch && method === 'POST' && path.endsWith('/start')) {
      return json(route, { ok: true });
    }
    if (botMatch && method === 'POST' && path.endsWith('/stop')) {
      return json(route, { ok: true });
    }
    if (botMatch && method === 'POST' && path.endsWith('/ai/trigger')) {
      return json(route, { ok: true, cycles: 1 });
    }
    if (botMatch && method === 'PATCH' && path.endsWith('/config')) {
      return json(route, { ok: true });
    }
    if (botMatch && method === 'GET' && path.endsWith('/history')) {
      return json(route, { trades: [] });
    }
    if (botMatch && method === 'GET' && path.endsWith('/ai/status')) {
      return json(route, { enabled: true, cycles: 10, last_trigger: new Date().toISOString() });
    }
    if (botMatch && method === 'GET' && path.endsWith('/ai/decisions')) {
      return json(route, { decisions: [] });
    }

    // ── Market Data ───────────────────────────────────────
    if (method === 'GET' && path.startsWith('/market/data/')) {
      const symbol = path.split('/').pop()!;
      return json(route, mockMarketData(symbol));
    }
    if (method === 'GET' && path === '/market/symbols/available') {
      return json(route, mockAvailableSymbols);
    }

    // ── Account Info ──────────────────────────────────────
    if (method === 'GET' && path === '/fleet/account') {
      return json(route, mockMT5Account);
    }

    // ── System Resources ──────────────────────────────────
    if (method === 'GET' && path === '/system/resources') {
      return json(route, mockSystemResources);
    }

    // ── Wizard ────────────────────────────────────────────
    if (method === 'POST' && path === '/fleet/wizard/generate') {
      const body = route.request().postDataJSON();
      return json(route, mockWizardResult(body));
    }

    // ── Setup API ─────────────────────────────────────────
    if (method === 'GET' && path === '/setup/status') {
      return json(route, mockSetupStatus);
    }
    if (method === 'POST' && path === '/setup/database/test') {
      return json(route, mockDbTestSuccess);
    }
    if (method === 'POST' && path === '/setup/database') {
      return json(route, { ok: true });
    }
    if (method === 'POST' && path === '/setup/api-keys') {
      return json(route, { ok: true });
    }
    if (method === 'POST' && path === '/setup/complete') {
      return json(route, { ok: true });
    }
    if (method === 'GET' && path === '/setup/config') {
      return json(route, { has_database: true, has_accounts: true, has_api_keys: true });
    }

    // ── Accounts ──────────────────────────────────────────
    if (method === 'GET' && path === '/accounts') {
      return json(route, { accounts: mockMT5Accounts, count: mockMT5Accounts.length });
    }
    if (method === 'POST' && path === '/accounts') {
      return json(route, { id: 'acct-new', ok: true });
    }
    const acctDeleteMatch = path.match(/^\/accounts\/(.+)$/);
    if (acctDeleteMatch && method === 'DELETE') {
      return json(route, { ok: true });
    }
    const acctSymbolsMatch = path.match(/^\/accounts\/(.+)\/symbols$/);
    if (acctSymbolsMatch && method === 'GET') {
      return json(route, mockAccountSymbols);
    }

    // ── Server health (Next.js API route, not mocked) ─────
    // Pass through Next.js API routes
    if (url.port === '3000' || url.hostname === 'localhost' && url.port !== '8000') {
      return route.continue();
    }

    // Fallback
    return route.abort('addressunreachable');
  });

  // Mock WebSocket connections (prevents connection errors)
  await page.route('ws://localhost:8000/ws', async (route) => {
    await route.abort();
  });
  await page.route('ws://localhost:8000/ws/bot/**', async (route) => {
    await route.abort();
  });
}

function json(route: Route, data: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  });
}
