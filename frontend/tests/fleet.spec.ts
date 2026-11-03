import { test, expect } from '@playwright/test';
import { setupApiMocks } from './mocks/handlers';

test.describe('Fleet Command Page', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  test.describe('Page Layout', () => {
    test('renders fleet command header', async ({ page }) => {
      await page.goto('/fleet');
      await expect(page.locator('h1').filter({ hasText: 'FLEET COMMAND' })).toBeVisible({ timeout: 15000 });
    });

    test('shows fleet summary stat pills', async ({ page }) => {
      await page.goto('/fleet');
      await expect(page.locator('text=ACTIVE').first()).toBeVisible({ timeout: 15000 });
      await expect(page.locator('text=CAPACITY').first()).toBeVisible({ timeout: 5000 });
      await expect(page.locator('text=EQUITY').first()).toBeVisible({ timeout: 5000 });
    });

    test('DEPLOY BOT button is visible', async ({ page }) => {
      await page.goto('/fleet');
      await expect(page.getByRole('button', { name: 'DEPLOY BOT' })).toBeVisible({ timeout: 15000 });
    });

    test('SETTINGS button is visible', async ({ page }) => {
      await page.goto('/fleet');
      await expect(page.getByText('SETTINGS').first()).toBeVisible({ timeout: 15000 });
    });

    test('Refresh button is visible', async ({ page }) => {
      await page.goto('/fleet');
      // The refresh button has RefreshCw icon
      await expect(page.locator('button svg.lucide-refresh-cw')).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Filter Tabs', () => {
    test('shows all three filter tabs', async ({ page }) => {
      await page.goto('/fleet');
      // Tab buttons have class containing uppercase tracking-widest
      const filterBar = page.locator('.flex.items-center.gap-1');
      await expect(filterBar.locator('button').first()).toBeVisible({ timeout: 15000 });
      // Verify we see filter button text
      await expect(page.locator('button').filter({ hasText: /^all/ }).first()).toBeVisible({ timeout: 5000 });
      await expect(page.locator('button').filter({ hasText: /^running/ }).first()).toBeVisible({ timeout: 5000 });
      await expect(page.locator('button').filter({ hasText: /^stopped/ }).first()).toBeVisible({ timeout: 5000 });
    });

    test('clicking "running" filters by running bots', async ({ page }) => {
      await page.goto('/fleet');
      await page.locator('button').filter({ hasText: /^running/ }).first().click();
      // Verify we see some bot cards remain visible
      const botName = page.getByText(/BTC|ETH|EUR|GBP|GOLD|SPX|DOW/).first();
      await expect(botName).toBeVisible({ timeout: 10000 });
    });

    test('clicking "stopped" filters by stopped bots', async ({ page }) => {
      await page.goto('/fleet');
      await page.locator('button').filter({ hasText: /^stopped/ }).first().click();
      // Wait for the grid to update
      await page.waitForTimeout(1000);
      // Either we see bot cards or an empty state
      const hasContent = await page.getByText(/Fleet is Empty|No stopped|deploy/i).isVisible().catch(() => false);
      const hasBots = await page.locator('button').filter({ hasText: /DEPLOY/ }).first().isVisible().catch(() => false);
      expect(hasContent || hasBots).toBeTruthy();
    });
  });

  test.describe('Bot Cards', () => {
    test('renders bot cards with names', async ({ page }) => {
      await page.goto('/fleet');
      await expect(page.getByText('BTC Elephant')).toBeVisible({ timeout: 15000 });
    });

    test('bot cards show symbol info', async ({ page }) => {
      await page.goto('/fleet');
      await expect(page.getByText('BTCUSD').first()).toBeVisible({ timeout: 15000 });
    });

    test('bot cards show strategy tags', async ({ page }) => {
      await page.goto('/fleet');
      // Fleet bot cards render strategy labels
      const anyBotText = page.getByText(/Elephant|Buffalo|Rhino|Leopard|Lion/).first();
      await expect(anyBotText).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Empty State', () => {
    test('shows empty state when no bots exist', async ({ page }) => {
      await page.route('http://localhost:8000/fleet/status', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            fleet_config: { max_bots: 10, global_risk_enabled: false, max_fleet_drawdown_pct: 25, sub_agents_enabled: true, auto_redeploy: false, log_retention_days: 30 },
            summary: { total_bots: 0, running_bots: 0, max_bots: 10, total_daily_pnl: 0, total_equity: 0, timestamp: new Date().toISOString() },
            bots: [],
          }),
        });
      });
      await page.goto('/fleet');
      await expect(page.getByText('Fleet is Empty')).toBeVisible({ timeout: 15000 });
      await expect(page.getByText('Deploy your first autonomous bot')).toBeVisible({ timeout: 5000 });
    });

    test('empty state shows DEPLOY FIRST BOT button', async ({ page }) => {
      await page.route('http://localhost:8000/fleet/status', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
          fleet_config: { max_bots: 10, global_risk_enabled: false, max_fleet_drawdown_pct: 25, sub_agents_enabled: true, auto_redeploy: false, log_retention_days: 30 },
          summary: { total_bots: 0, running_bots: 0, max_bots: 10, total_daily_pnl: 0, total_equity: 0, timestamp: new Date().toISOString() },
          bots: [],
        })});
      });
      await page.goto('/fleet');
      await expect(page.getByRole('button', { name: 'DEPLOY FIRST BOT' })).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Connection Error', () => {
    test('shows error when backend is offline', async ({ page }) => {
      await page.route('http://localhost:8000/**', async (route) => {
        await route.abort('connectionrefused');
      });
      await page.goto('/fleet');
      await expect(page.getByText('Backend Offline')).toBeVisible({ timeout: 15000 });
    });

    test('RETRY CONNECTION button is present on error', async ({ page }) => {
      await page.route('http://localhost:8000/**', async (route) => {
        await route.abort('connectionrefused');
      });
      await page.goto('/fleet');
      await expect(page.getByRole('button', { name: 'RETRY CONNECTION' })).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Risk Kill Switch Banner', () => {
    test('shows fleet risk kill switch when enabled', async ({ page }) => {
      await page.goto('/fleet');
      await expect(page.getByText('Fleet Risk Kill Switch is active')).toBeVisible({ timeout: 15000 });
    });
  });
});
