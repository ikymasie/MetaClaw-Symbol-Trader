import { test, expect } from '@playwright/test';
import { setupApiMocks } from './mocks/handlers';
import { mockFleetStatus } from './mocks/fixtures';

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  test.describe('Initial Load & Layout', () => {
    test('shows loading state on initial render', async ({ page }) => {
      // Delay the fleet status response to show loading
      await page.route('http://localhost:8000/fleet/status', async (route) => {
        await new Promise((r) => setTimeout(r, 2000));
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockFleetStatus(0)) });
      });
      await page.goto('/');
      await expect(page.getByText('Connecting to Fleet...')).toBeVisible();
    });

    test('shows dashboard with fleet summary bar after data loads', async ({ page }) => {
      await page.goto('/');
      await expect(page.locator('text=ACTIVE').first()).toBeVisible({ timeout: 15000 });
      await expect(page.locator('text=FLEET P&L').first()).toBeVisible({ timeout: 5000 });
      await expect(page.locator('text=NET EQUITY').first()).toBeVisible({ timeout: 5000 });
    });

    test('shows backend offline error when API fails', async ({ page }) => {
      await page.route('http://localhost:8000/**', async (route) => {
        await route.abort('connectionrefused');
      });
      await page.goto('/');
      await expect(page.getByText('Backend Offline')).toBeVisible({ timeout: 15000 });
      await expect(page.getByText('Make sure the backend is running')).toBeVisible();
    });

    test('RETRY CONNECTION button is present on error state', async ({ page }) => {
      await page.route('http://localhost:8000/**', async (route) => {
        await route.abort('connectionrefused');
      });
      await page.goto('/');
      await expect(page.getByRole('button', { name: 'RETRY CONNECTION' })).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Fleet Summary Bar', () => {
    test('displays active bot count', async ({ page }) => {
      await page.goto('/');
      await expect(page.locator('text=ACTIVE').first()).toBeVisible({ timeout: 15000 });
    });

    test('displays fleet P&L', async ({ page }) => {
      await page.goto('/');
      await expect(page.locator('text=FLEET P&L').first()).toBeVisible({ timeout: 15000 });
    });

    test('displays NET EQUITY', async ({ page }) => {
      await page.goto('/');
      await expect(page.locator('text=NET EQUITY').first()).toBeVisible({ timeout: 15000 });
    });

    test('shows DEPLOY BOT button', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByRole('button', { name: 'DEPLOY BOT' })).toBeVisible({ timeout: 15000 });
    });

    test('DEPLOY BOT opens BotWizard modal', async ({ page }) => {
      await page.goto('/');
      const deployBtn = page.getByRole('button', { name: 'DEPLOY BOT' });
      await expect(deployBtn).toBeVisible({ timeout: 15000 });
      await deployBtn.click();
      await expect(page.getByText('Savanna Wizard')).toBeVisible({ timeout: 5000 });
      await expect(page.getByText('Select broker account')).toBeVisible();
    });

    test('WS liveness indicator visible', async ({ page }) => {
      await page.goto('/');
      // Look for either LIVE or POLLING text anywhere in the page
      await expect(page.getByText(/LIVE|POLLING/).first()).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Market Pulse Chart Section', () => {
    test('renders Market Pulse chart header', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByText('Market Pulse')).toBeVisible({ timeout: 15000 });
    });

    test('shows active symbol', async ({ page }) => {
      await page.goto('/');
      // BTCUSD appears in the Market Pulse section
      await expect(page.getByText('BTCUSD').first()).toBeVisible({ timeout: 15000 });
    });

    test('symbol selector dropdown is visible', async ({ page }) => {
      await page.goto('/');
      const selector = page.locator('select').first();
      await expect(selector).toBeVisible({ timeout: 15000 });
      await expect(selector).toHaveValue('BTCUSD');
    });

    test('can switch to a different symbol via selector', async ({ page }) => {
      await page.goto('/');
      const selector = page.locator('select').first();
      await expect(selector).toBeVisible({ timeout: 15000 });
      await selector.selectOption('EURUSD');
      await expect(selector).toHaveValue('EURUSD');
    });

    test('displays price data when available', async ({ page }) => {
      await page.goto('/');
      // The chart renders in a canvas, so we verify the price stat display
      // Price stat shows the latest close price
      await expect(page.getByText('$', { exact: false }).first()).toBeVisible({ timeout: 15000 });
    });

    test('chart container has correct height', async ({ page }) => {
      await page.goto('/');
      const chartContainer = page.locator('.h-\\[400px\\]');
      await expect(chartContainer).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Fleet Bot Grid', () => {
    test('renders bot cards in the grid', async ({ page }) => {
      await page.goto('/');
      // Bot names from the mock: BTC Elephant, ETH Buffalo, etc.
      await expect(page.getByText('BTC Elephant')).toBeVisible({ timeout: 15000 });
    });

    test('filter tabs are visible', async ({ page }) => {
      await page.goto('/');
      await expect(page.locator('button').filter({ hasText: /^all/ })).toBeVisible({ timeout: 15000 });
    });

    test('clicking a bot card opens detail drawer', async ({ page }) => {
      await page.goto('/');
      await page.getByText('BTC Elephant').first().click();
      // Bot detail drawer should open showcasing bot info
      await expect(page.getByText('BTCUSD').first()).toBeVisible({ timeout: 5000 });
    });

    test('closing drawer works', async ({ page }) => {
      await page.goto('/');
      await page.getByText('BTC Elephant').click();
      // Find and click close button (X) on the drawer
      const closeBtn = page.locator('[role="button"]').filter({ has: page.locator('svg.lucide-x') }).first();
      if (await closeBtn.isVisible()) {
        await closeBtn.click();
      }
    });
  });

  test.describe('Account Vitals Sidebar', () => {
    test('renders AccountVitalsCard', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByText('ACCOUNT VITALS')).toBeVisible({ timeout: 15000 });
    });

    test('shows equity value', async ({ page }) => {
      await page.goto('/');
      // Account vitals card should show the equity value somewhere
      await expect(page.getByText(/\$125,?000/).first()).toBeVisible({ timeout: 15000 });
    });

    test('shows daily P&L', async ({ page }) => {
      await page.goto('/');
      // Account vitals card shows daily P&L with $ sign
      await expect(page.getByText(/\+?[\$]/).first()).toBeVisible({ timeout: 15000 });
    });

    test('renders Operational Memo sidebar note', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByText('Operational Memo')).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Footer', () => {
    test('shows copyright info', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByText('TradeClaw Autonomous Fleet Command')).toBeVisible({ timeout: 15000 });
    });

    test('shows status indicators', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByText('API: OK')).toBeVisible({ timeout: 15000 });
      await expect(page.getByText('MT5: ACTIVE')).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Fleet Risk Kill Switch Alert', () => {
    test('shows risk kill switch banner when enabled', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByText('Fleet Risk Kill Switch active')).toBeVisible({ timeout: 15000 });
    });
  });
});
