import { test, expect } from '@playwright/test';
import { setupApiMocks } from './mocks/handlers';

test.describe('Setup Wizard', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  test('renders the setup wizard on /setup', async ({ page }) => {
    await page.goto('/setup');
    await expect(page.locator('h1')).toContainText('TradeClaw Setup');
  });

  test('shows all 4 step indicators', async ({ page }) => {
    await page.goto('/setup');
    await expect(page.getByRole('button', { name: 'Database' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'MT5 Accounts' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'AI Brain' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Launch' })).toBeVisible();
  });

  test('shows progress bar', async ({ page }) => {
    await page.goto('/setup');
    await expect(page.locator('[role="progressbar"]')).toBeVisible();
  });

  test.describe('Step 1: Database', () => {
    test('renders database connection form', async ({ page }) => {
      await page.goto('/setup');
      await expect(page.getByText('PostgreSQL Connection')).toBeVisible();
      await expect(page.locator('#db-url')).toBeVisible();
    });

    test('can type a database URL and test connection', async ({ page }) => {
      await page.goto('/setup');
      const dbInput = page.locator('#db-url');
      await dbInput.fill('postgresql://user:pass@host/db');
      await expect(dbInput).toHaveValue('postgresql://user:pass@host/db');

      const testBtn = page.getByRole('button', { name: 'Test' });
      await expect(testBtn).toBeEnabled();
      await testBtn.click();
      await expect(page.getByText('Connected to PostgreSQL successfully')).toBeVisible();
    });

    test('Save & Continue is disabled without a URL', async ({ page }) => {
      await page.goto('/setup');
      await expect(page.getByRole('button', { name: 'Save & Continue' })).toBeDisabled();
    });

    test('Save & Continue enables after entering a URL', async ({ page }) => {
      await page.goto('/setup');
      await page.locator('#db-url').fill('postgresql://user:pass@host/db');
      await expect(page.getByRole('button', { name: 'Save & Continue' })).toBeEnabled();
    });
  });

  test.describe('Step 2: MT5 Accounts', () => {
    test('advances to accounts step after database save', async ({ page }) => {
      await page.goto('/setup');
      await page.locator('#db-url').fill('postgresql://user:pass@host/db');
      await page.getByRole('button', { name: 'Save & Continue' }).click();
      await expect(page.getByText('MT5 Broker Accounts')).toBeVisible();
    });

    test('shows add account form when clicking add', async ({ page }) => {
      await page.goto('/setup');
      await page.locator('#db-url').fill('postgresql://user:pass@host/db');
      await page.getByRole('button', { name: 'Save & Continue' }).click();
      // After save, we land on accounts step. Since mock has accounts pre-loaded,
      // the form is NOT auto-shown; click "Add Another Account" to reveal it
      const addBtn = page.getByRole('button', { name: 'Add Another Account' });
      await addBtn.click();
      await expect(page.getByPlaceholder('My Broker')).toBeVisible({ timeout: 3000 });
      await expect(page.getByPlaceholder('MetaQuotes-Demo')).toBeVisible();
    });

    test('can fill out account form fields', async ({ page }) => {
      await page.goto('/setup');
      await page.locator('#db-url').fill('postgresql://user:pass@host/db');
      await page.getByRole('button', { name: 'Save & Continue' }).click();
      // Click "Add Another Account" to show the form
      await page.getByRole('button', { name: 'Add Another Account' }).click();

      await page.getByPlaceholder('My Broker').fill('Test Broker');
      await page.getByPlaceholder('MetaQuotes-Demo').fill('ICMarkets-Demo');
      await page.getByPlaceholder('12345678').fill('12345678');

      await expect(page.getByPlaceholder('My Broker')).toHaveValue('Test Broker');
      await expect(page.getByPlaceholder('MetaQuotes-Demo')).toHaveValue('ICMarkets-Demo');
    });

    test('password visibility toggle works', async ({ page }) => {
      await page.goto('/setup');
      await page.locator('#db-url').fill('postgresql://user:pass@host/db');
      await page.getByRole('button', { name: 'Save & Continue' }).click();
      // Click "Add Another Account" to show the form
      await page.getByRole('button', { name: 'Add Another Account' }).click();

      const pwInput = page.locator('input[type="password"]');
      await pwInput.fill('secret123');
      // Click the eye icon to toggle visibility
      await page.locator('button').filter({ has: page.locator('svg.lucide-eye') }).first().click();
      await expect(page.locator('input[type="text"]').first()).toBeVisible();
    });

    test('Continue button is enabled when accounts exist', async ({ page }) => {
      await page.goto('/setup');
      await page.locator('#db-url').fill('postgresql://user:pass@host/db');
      await page.getByRole('button', { name: 'Save & Continue' }).click();
      // The mock returns 2 pre-existing accounts, so Continue should be enabled
      await expect(page.getByRole('button', { name: 'Continue' })).toBeEnabled({ timeout: 3000 });
    });
  });

  test.describe('Step 3: AI Brain / API Keys', () => {
    test('navigates through all steps to API keys', async ({ page }) => {
      await page.goto('/setup');
      await page.locator('#db-url').fill('postgresql://user:pass@host/db');
      await page.getByRole('button', { name: 'Save & Continue' }).click();

      // Directly navigate to API keys step
      await page.getByRole('button', { name: 'AI Brain' }).click();

      await expect(page.getByText('Choose your AI provider')).toBeVisible();
    });

    test('shows all 4 provider options', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'AI Brain' }).click();

      await expect(page.getByText('DeepSeek').first()).toBeVisible();
      await expect(page.getByText('Anthropic').first()).toBeVisible();
      await expect(page.getByText('Google').first()).toBeVisible();
      await expect(page.getByText('OpenAI').first()).toBeVisible();
    });

    test('DeepSeek is selected by default', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'AI Brain' }).click();
      await expect(page.getByLabel('Deep Think Model')).toHaveValue('deepseek-v4-pro');
    });

    test('can switch provider and see model list update', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'AI Brain' }).click();

      // Click Anthropic
      await page.getByText('Anthropic').click();
      await expect(page.getByLabel('Deep Think Model')).toHaveValue('claude-opus-4-7');
      await expect(page.getByLabel('Quick Think Model')).toHaveValue('claude-haiku-4-5');
    });

    test('API key field label changes with provider', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'AI Brain' }).click();

      await expect(page.getByText('DeepSeek API Key')).toBeVisible();

      await page.getByText('Google').click();
      await expect(page.getByText('Google AI (Gemini) API Key')).toBeVisible();
    });

    test('can type an API key', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'AI Brain' }).click();

      await page.locator('#api-key').fill('sk-test-key-12345');
      await expect(page.locator('#api-key')).toHaveValue('sk-test-key-12345');
    });

    test('show/hide keys toggle works', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'AI Brain' }).click();

      const apiKeyInput = page.locator('#api-key');
      await apiKeyInput.fill('sk-secret');

      // Click show/hide toggle
      await page.getByText('Show keys').click();
      await expect(page.locator('#api-key')).toHaveAttribute('type', 'text');
    });

    test('Skip button available when no keys entered', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'AI Brain' }).click();
      await expect(page.getByRole('button', { name: 'Skip' })).toBeVisible();
    });

    test('Back button returns to accounts step', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'AI Brain' }).click();
      await page.getByRole('button', { name: 'Back' }).click();

      await expect(page.getByText('MT5 Broker Accounts')).toBeVisible();
    });
  });

  test.describe('Step 4: Launch / Complete', () => {
    test('shows review when navigating to complete step', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'Launch' }).click();
      await expect(page.getByText('Ready to Launch')).toBeVisible();
    });

    test('shows configuration checklist', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'Launch' }).click();

      // Check for review items
      await expect(page.getByText('Database connected').first()).toBeVisible();
      await expect(page.getByText('MT5 account').first()).toBeVisible();
      await expect(page.getByText('API keys configured').first()).toBeVisible();
    });

    test('Launch button is visible', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'Launch' }).click();
      await expect(page.getByRole('button', { name: 'Launch TradeClaw' })).toBeVisible();
    });

    test('Back returns to API keys step', async ({ page }) => {
      await page.goto('/setup');
      await page.getByRole('button', { name: 'Launch' }).click();
      await page.getByRole('button', { name: 'Back' }).click();

      // Should navigate back to API keys
      await expect(page.getByText('Choose your AI provider')).toBeVisible();
    });
  });

  test.describe('Post-Setup Settings Panel', () => {
    test.beforeEach(async ({ page }) => {
      // Override setup status to show settings panel
      await page.route('http://localhost:8000/setup/status', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            setup_complete: true,
            has_database: true,
            has_accounts: true,
            has_api_keys: true,
            account_count: 2,
          }),
        });
      });
      await page.route('http://localhost:8000/accounts', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            accounts: [
              { id: 'acct-1', label: 'Demo Broker', mt5_login: 12345678, mt5_server: 'MetaQuotes-Demo', is_default: true, created_at: '2025-01-01T00:00:00Z' },
              { id: 'acct-2', label: 'Live Broker', mt5_login: 87654321, mt5_server: 'ICMarkets-Demo', is_default: false, created_at: '2025-01-10T00:00:00Z' },
            ],
            count: 2,
          }),
        });
      });
    });

    test('shows settings panel when setup is complete', async ({ page }) => {
      await page.goto('/setup');
      await expect(page.getByText('Settings')).toBeVisible();
      await expect(page.getByText('System Active')).toBeVisible();
    });

    test('has three tabs: MT5 Accounts, AI Brain, Database', async ({ page }) => {
      await page.goto('/setup');
      await expect(page.getByRole('button', { name: 'MT5 Accounts' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'AI Brain' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Database' })).toBeVisible();
    });

    test('has Dashboard button linking to home', async ({ page }) => {
      await page.goto('/setup');
      const dashboardLink = page.getByRole('button', { name: 'Dashboard' });
      await expect(dashboardLink).toBeVisible();
    });
  });
});
