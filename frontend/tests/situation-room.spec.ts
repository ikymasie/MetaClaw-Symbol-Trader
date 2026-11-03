import { test, expect } from '@playwright/test';
import { setupApiMocks } from './mocks/handlers';

test.describe('Situation Room', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  test.describe('Page Layout', () => {
    test('renders Situation Room header', async ({ page }) => {
      await page.goto('/situation-room');
      await expect(page.locator('h1').filter({ hasText: 'Situation Room' })).toBeVisible({ timeout: 15000 });
    });

    test('shows AWAITING OPERATIONAL UPLINK when no bot selected', async ({ page }) => {
      await page.goto('/situation-room');
      await expect(page.getByText('AWAITING OPERATIONAL UPLINK')).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Bot Selector', () => {
    test('bot selector dropdown is visible', async ({ page }) => {
      await page.goto('/situation-room');
      const selector = page.locator('select');
      await expect(selector).toBeVisible({ timeout: 15000 });
      await expect(selector.locator('option').first()).toHaveText('SELECT BOT TO MONITOR');
    });

    test('selector contains fleet bots as options', async ({ page }) => {
      await page.goto('/situation-room');
      const selector = page.locator('select');
      await expect(selector).toBeVisible({ timeout: 15000 });

      // Check options include bot names
      const options = selector.locator('option');
      await expect(options.nth(1)).toContainText('BTC Elephant');
    });

    test('selecting a bot shows its symbol in subheader', async ({ page }) => {
      await page.goto('/situation-room');
      const selector = page.locator('select');
      await selector.selectOption({ index: 1 });

      // Feed label should include the bot symbol
      await expect(page.getByText('FEED:').first()).toBeVisible({ timeout: 5000 });
      await expect(page.locator('p').filter({ hasText: /BTCUSD/ }).first()).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Signal Scanning (Idle State)', () => {
    test('shows SignalScanning component before bot is selected', async ({ page }) => {
      await page.goto('/situation-room');
      // SignalScanning shows "Scanning for Alpha Signals" heading
      await expect(page.getByText('Scanning for Alpha Signals').or(page.getByText('Select a bot'))).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Status Bridge', () => {
    test('status bridge appears when a bot is selected', async ({ page }) => {
      await page.goto('/situation-room');
      const selector = page.locator('select');
      await selector.selectOption({ index: 1 });

      // StatusBridge should appear in the dashboard view
      await expect(page.locator('text=DELIBERATION CYCLE').or(page.locator('text=UPSTREAM'))).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Orbital Nexus (Agent Grid)', () => {
    test('orbital nexus renders when bot is selected', async ({ page }) => {
      await page.goto('/situation-room');
      const selector = page.locator('select');
      await selector.selectOption({ index: 1 });

      // The OrbitalNexus renders the 6-agent war room
      await expect(page.locator('text=UPSTREAM')).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Executioner Panel', () => {
    test('executioner panel renders when bot is selected', async ({ page }) => {
      await page.goto('/situation-room');
      const selector = page.locator('select');
      await selector.selectOption({ index: 1 });

      // The ExecutionerPanel shows verdict information on the right
      await expect(page.locator('text=VERDICT').or(page.locator('text=EXECUTION'))).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Live Clock', () => {
    test('shows current time in header', async ({ page }) => {
      await page.goto('/situation-room');
      await page.waitForTimeout(2000);
      // Clock should show HH:MM:SS format
      const clockEl = page.locator('text=/\\d{2}:\\d{2}:\\d{2}/');
      await expect(clockEl).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Top Stat Pills', () => {
    test('shows stat pills when bot is selected', async ({ page }) => {
      await page.goto('/situation-room');
      const selector = page.locator('select');
      await selector.selectOption({ index: 1 });

      await expect(page.locator('text=UPSTREAM').first()).toBeVisible({ timeout: 5000 });
      await expect(page.locator('text=QUORUM').first()).toBeVisible({ timeout: 5000 });
      await expect(page.locator('text=VETOED').first()).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Footer', () => {
    test('shows protocol and cycle info in footer', async ({ page }) => {
      await page.goto('/situation-room');
      await expect(page.getByText('MAS V2 PROTOCOL')).toBeVisible({ timeout: 15000 });
      await expect(page.getByText('CYCLES:')).toBeVisible({ timeout: 5000 });
    });
  });
});
