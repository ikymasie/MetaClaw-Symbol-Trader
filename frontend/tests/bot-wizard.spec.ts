import { test, expect, type Page } from '@playwright/test';
import { setupApiMocks } from './mocks/handlers';

test.describe('Bot Wizard Deploy Flow', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  test.describe('Opening the Wizard', () => {
    test('DEPLOY BOT on dashboard opens BotWizard', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await expect(page.getByText('Savanna Wizard')).toBeVisible({ timeout: 5000 });
      await expect(page.getByText('AI-Powered Bot Forge')).toBeVisible();
    });

    test('DEPLOY BOT on fleet page opens BotWizard', async ({ page }) => {
      await page.goto('/fleet');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await expect(page.getByText('Savanna Wizard')).toBeVisible({ timeout: 5000 });
    });

    test('DEPLOY FIRST BOT on empty fleet opens BotWizard', async ({ page }) => {
      await page.route('http://localhost:8000/fleet/status', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
          fleet_config: { max_bots: 10, global_risk_enabled: false, max_fleet_drawdown_pct: 25, sub_agents_enabled: true, auto_redeploy: false, log_retention_days: 30 },
          summary: { total_bots: 0, running_bots: 0, max_bots: 10, total_daily_pnl: 0, total_equity: 0, timestamp: new Date().toISOString() },
          bots: [],
        })});
      });
      await page.goto('/fleet');
      await page.getByRole('button', { name: 'DEPLOY FIRST BOT' }).click();
      await expect(page.getByText('Savanna Wizard')).toBeVisible({ timeout: 5000 });
    });

    test('clicking backdrop closes the wizard', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await expect(page.getByText('Savanna Wizard')).toBeVisible({ timeout: 5000 });

      // Click the backdrop overlay
      const backdrop = page.locator('.fixed.inset-0.z-50 > .absolute.inset-0');
      await backdrop.first().click({ position: { x: 10, y: 10 }, force: true });
      await expect(page.getByText('Savanna Wizard')).not.toBeVisible({ timeout: 3000 });
    });

    test('clicking X button closes the wizard', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await expect(page.getByText('Savanna Wizard')).toBeVisible({ timeout: 5000 });

      // Click the X button in the modal header
      const modal = page.locator('.fixed.inset-0.z-50');
      const closeBtn = modal.locator('button').filter({ has: page.locator('svg.lucide-x') });
      await closeBtn.click();
      await expect(page.getByText('Savanna Wizard')).not.toBeVisible({ timeout: 3000 });
    });
  });

  test.describe('Step 1: Select Broker Account', () => {
    test('shows available broker accounts', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await expect(page.getByText('Select broker account')).toBeVisible();
      await expect(page.getByText('Demo Broker')).toBeVisible();
      await expect(page.getByText('Live Broker')).toBeVisible();
    });

    test('highlights default account', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await expect(page.getByText('Default')).toBeVisible();
    });

    test('clicking an account advances to market step', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();
      await expect(page.getByText('Choose your market')).toBeVisible({ timeout: 5000 });
    });

    test('shows no accounts message when empty', async ({ page }) => {
      await page.route('http://localhost:8000/accounts', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ accounts: [], count: 0 }) });
      });
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await expect(page.getByText('No MT5 accounts configured')).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Step 2: Choose Market', () => {
    test('shows market categories', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();

      // Should see market categories
      await expect(page.getByText('Crypto').first()).toBeVisible({ timeout: 5000 });
      await expect(page.getByText('Forex Majors')).toBeVisible({ timeout: 5000 });
    });

    test('category search filters markets', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();

      const searchInput = page.getByPlaceholder('Search markets or symbols...');
      await searchInput.fill('Crypto');

      await expect(page.getByText('Crypto')).toBeVisible();
      await expect(page.getByText('Forex Majors')).not.toBeVisible({ timeout: 3000 });
    });

    test('back button returns to account step', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();

      // Click back button
      await page.locator('button').filter({ has: page.locator('svg.lucide-chevron-left') }).first().click();
      await expect(page.getByText('Select broker account')).toBeVisible({ timeout: 3000 });
    });
  });

  test.describe('Step 3: Pick Symbol', () => {
    test('shows symbols for selected category', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();
      // Wait for market step
      await expect(page.getByText('Choose your market')).toBeVisible({ timeout: 5000 });
      // Click Crypto
      await page.locator('button').filter({ hasText: 'Crypto' }).first().click();

      // Should see symbol picker
      await expect(page.getByText('Pick a symbol')).toBeVisible({ timeout: 5000 });
      // BTCUSD and ETHUSD should appear as symbol buttons
      await expect(page.getByText('BTCUSD').first()).toBeVisible({ timeout: 5000 });
    });

    test('symbol search filters results', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();
      await expect(page.getByText('Choose your market')).toBeVisible({ timeout: 5000 });
      await page.locator('button').filter({ hasText: 'Crypto' }).first().click();
      await expect(page.getByText('Pick a symbol')).toBeVisible({ timeout: 5000 });

      const searchInput = page.getByPlaceholder('Search symbols...');
      await searchInput.fill('BTC');

      await expect(page.getByText('BTCUSD').first()).toBeVisible({ timeout: 3000 });
    });

    test('manual symbol entry is available', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();
      await expect(page.getByText('Choose your market')).toBeVisible({ timeout: 5000 });
      await page.locator('button').filter({ hasText: 'Crypto' }).first().click();
      await expect(page.getByText('Pick a symbol')).toBeVisible({ timeout: 5000 });

      await expect(page.getByPlaceholder('Manual entry e.g. BTCUSD')).toBeVisible();
    });

    test('can type a custom symbol and advance', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();
      await expect(page.getByText('Choose your market')).toBeVisible({ timeout: 5000 });
      await page.locator('button').filter({ hasText: 'Crypto' }).first().click();
      await expect(page.getByText('Pick a symbol')).toBeVisible({ timeout: 5000 });

      await page.getByPlaceholder('Manual entry e.g. BTCUSD').fill('DOGEUSD');
      // The Next button should be enabled
      const nextBtn = page.locator('button').filter({ hasText: 'Next' }).last();
      await expect(nextBtn).toBeVisible({ timeout: 3000 });
    });
  });

  test.describe('Step 4: Choose Spirit Animal (Personality)', () => {
    /** Navigate to personality step from fleet page */
    async function goToPersonality(page: Page) {
      await page.goto('/fleet');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();
      await expect(page.getByText('Choose your market')).toBeVisible({ timeout: 5000 });
      await page.locator('button').filter({ hasText: 'Crypto' }).first().click();
      await expect(page.getByText('Pick a symbol')).toBeVisible({ timeout: 5000 });
      await page.locator('button').filter({ hasText: 'BTCUSD' }).first().click();
      await expect(page.getByText('Choose your spirit animal')).toBeVisible({ timeout: 5000 });
    }

    test('shows all 5 spirit animal personalities', async ({ page }) => {
      await goToPersonality(page);
      await expect(page.getByText('Patient Elephant')).toBeVisible({ timeout: 3000 });
      await expect(page.getByText('Grazing Buffalo')).toBeVisible();
      await expect(page.getByText('Steady Rhino')).toBeVisible();
      await expect(page.getByText('Prowling Leopard')).toBeVisible();
      await expect(page.getByText('Hungry Lion')).toBeVisible();
    });

    test('Forge My Bot button is disabled without selection', async ({ page }) => {
      await goToPersonality(page);
      await expect(page.getByRole('button', { name: 'Forge My Bot' })).toBeDisabled();
    });

    test('selecting a personality enables Forge button', async ({ page }) => {
      await goToPersonality(page);
      await page.getByText('Patient Elephant').click();
      await expect(page.getByRole('button', { name: 'Forge My Bot' })).toBeEnabled({ timeout: 3000 });
    });
  });

  test.describe('Step 5: AI Forge (Loading)', () => {
    /** Navigate to personality step and click Forge */
    async function goToForge(page: Page) {
      await page.goto('/fleet');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();
      await expect(page.getByText('Choose your market')).toBeVisible({ timeout: 5000 });
      await page.locator('button').filter({ hasText: 'Crypto' }).first().click();
      await expect(page.getByText('Pick a symbol')).toBeVisible({ timeout: 5000 });
      await page.locator('button').filter({ hasText: 'BTCUSD' }).first().click();
      await expect(page.getByText('Choose your spirit animal')).toBeVisible({ timeout: 5000 });
      await page.getByText('Patient Elephant').click();
    }

    test('shows forge animation after clicking Forge My Bot', async ({ page }) => {
      await goToForge(page);
      // Delay forge response so we can see the animation
      await page.route('http://localhost:8000/fleet/wizard/generate', async (route) => {
        await new Promise((r) => setTimeout(r, 2000));
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            name: 'BTCUSD Patient Elephant', description: 'Test', personality: 'elephant', animal: 'Elephant',
            symbol: 'BTCUSD', category: 'Crypto', ai_generated: true,
            config: { symbol: 'BTCUSD', strategy: 'mean_reversion', capital_allocation: 10000, qty: 0.01, stop_loss_pct: 1.5, max_daily_drawdown_pct: 5, bb_period: 20, bb_std_dev: 2, ai_brain_enabled: true, ai_interval_minutes: 15, sub_agents: [], fib_enabled: true, leverage_mode_enabled: false, short_selling_enabled: true, auto_start: true, tags: [] },
          }),
        });
      });

      await page.getByRole('button', { name: 'Forge My Bot' }).click();
      await expect(page.getByText('AI Forge Active')).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Step 6: Review & Deploy', () => {
    /** Navigate through entire wizard up to the review step */
    async function goToReview(page: Page) {
      await page.goto('/fleet');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();
      await page.getByText('Demo Broker').click();
      await expect(page.getByText('Choose your market')).toBeVisible({ timeout: 5000 });
      await page.locator('button').filter({ hasText: 'Crypto' }).first().click();
      await expect(page.getByText('Pick a symbol')).toBeVisible({ timeout: 5000 });
      await page.locator('button').filter({ hasText: 'BTCUSD' }).first().click();
      await expect(page.getByText('Choose your spirit animal')).toBeVisible({ timeout: 5000 });
      await page.getByText('Patient Elephant').click();
      await page.getByRole('button', { name: 'Forge My Bot' }).click();
      // Wait for review to load
      await expect(page.getByText('Capital Allocation')).toBeVisible({ timeout: 15000 });
    }

    test('shows review page with bot details after forge completes', async ({ page }) => {
      await goToReview(page);
      await expect(page.getByText('AI Generated').or(page.getByText('AI Generated', { exact: false }))).toBeVisible({ timeout: 5000 });
    });

    test('shows bot config stats grid', async ({ page }) => {
      await goToReview(page);
      await expect(page.getByText('Strategy').first()).toBeVisible({ timeout: 5000 });
      await expect(page.getByText('Agents').first()).toBeVisible({ timeout: 5000 });
    });

    test('volume slider is present', async ({ page }) => {
      await goToReview(page);
      await expect(page.getByText('Volume (Lot Size)')).toBeVisible({ timeout: 5000 });
    });

    test('capital allocation input is present', async ({ page }) => {
      await goToReview(page);
      await expect(page.getByText('Capital Allocation')).toBeVisible({ timeout: 15000 });
    });

    test('leverage mode toggle is present', async ({ page }) => {
      await goToReview(page);
      await expect(page.getByText('Leverage Mode')).toBeVisible({ timeout: 5000 });
    });

    test('DEPLOY BOT submits and closes wizard', async ({ page }) => {
      await goToReview(page);
      // The modal DEPLOY BOT button should be in the footer
      const modalFooter = page.locator('.fixed.inset-0.z-50');
      const deployBtnModal = modalFooter.getByRole('button', { name: 'DEPLOY BOT' });
      await deployBtnModal.click();
      // Wizard should close after deployment
      await expect(page.getByText('Savanna Wizard')).not.toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Step Indicator', () => {
    test('shows step indicator in wizard header', async ({ page }) => {
      await page.goto('/');
      await page.getByRole('button', { name: 'DEPLOY BOT' }).click();

      // Check for step labels (the step indicator shows abbreviated labels)
      const stepEl = page.locator('.flex.items-center.gap-1').first();
      // Just verify the step indicator section exists with step labels
      await expect(stepEl).toBeVisible({ timeout: 3000 });
    });
  });
});
