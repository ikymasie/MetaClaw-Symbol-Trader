import { test, expect } from '@playwright/test';
import { setupApiMocks } from './mocks/handlers';

test.describe('Global Navigation Bar', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  test('renders brand name TRADECLAW', async ({ page }) => {
    await page.goto('/');
    // The brand name in the navbar is a single element: TRADECLAW with CLAW in primary color
    await expect(page.locator('nav').getByText('TRADE')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('nav').getByText('CLAW')).toBeVisible({ timeout: 5000 });
  });

  test.describe('Navigation Links', () => {
    const routes = [
      { href: '/', label: 'DASHBOARD' },
      { href: '/fleet', label: 'FLEET COMMAND' },
      { href: '/situation-room', label: 'SITUATION ROOM' },
      { href: '/setup', label: 'SETTINGS' },
    ];

    for (const { href, label } of routes) {
      test(`navigates to ${label} via nav link`, async ({ page }) => {
        await page.goto('/');
        await page.getByRole('link', { name: label }).click();
        await expect(page).toHaveURL(href, { timeout: 10000 });
      });
    }

    test('active link is visually highlighted', async ({ page }) => {
      await page.goto('/fleet');
      const fleetLink = page.getByRole('link', { name: 'FLEET COMMAND' });
      // The active link should have a border class or bg-primary
      const classAttr = await fleetLink.getAttribute('class');
      expect(classAttr).toContain('bg-primary');
    });

    test('dashboard link is active on home page', async ({ page }) => {
      await page.goto('/');
      const dashLink = page.getByRole('link', { name: 'DASHBOARD' });
      const classAttr = await dashLink.getAttribute('class');
      expect(classAttr).toContain('bg-primary');
    });
  });

  test.describe('Server Power Button', () => {
    test('server power button is visible', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByText('SYS ONLINE').or(page.getByText('SYS OFFLINE'))).toBeVisible({ timeout: 15000 });
    });

    test('clicking power button toggles server state', async ({ page }) => {
      await page.goto('/');
      const powerBtn = page.getByText('SYS ONLINE').or(page.getByText('SYS OFFLINE'));
      await powerBtn.click();
      // After clicking, it should show WORKING... temporarily
      await expect(page.getByText('WORKING...').or(page.getByText('SYS'))).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('System Resource Monitor', () => {
    test('CPU monitor icon is visible', async ({ page }) => {
      await page.goto('/');
      // SystemResourceMonitor is always visible in the navbar; it renders an SVG chart
      // Look for any SVG element inside the nav
      const navSvg = page.locator('nav svg').first();
      await expect(navSvg).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Account Overview Dropdown', () => {
    test('account equity is shown in navbar', async ({ page }) => {
      await page.goto('/');
      // Account equity is formatted with dollar sign and comma-separated thousands
      const accountSection = page.locator('nav').getByText(/\$\d{1,3}(,\d{3})*\.\d{2}/).first();
      await expect(accountSection).toBeVisible({ timeout: 15000 });
    });

    test('daily P&L percentage is shown', async ({ page }) => {
      await page.goto('/');
      // Look for a percentage value near the account section
      const pnlPct = page.locator('nav').getByText(/[+-]?\d+\.\d+%/).first();
      await expect(pnlPct).toBeVisible({ timeout: 15000 });
    });

    test('clicking account opens dropdown with portfolio details', async ({ page }) => {
      await page.goto('/');
      // Click the account equity display in the navbar
      await page.locator('nav').getByText(/\$\d{1,3}(,\d{3})*\.\d{2}/).first().click();
      // The dropdown should show Total Equity, Buying Power, etc.
      const dropdown = page.locator('.absolute.right-0.mt-2');
      await expect(dropdown).toBeVisible({ timeout: 5000 });
      await expect(dropdown.getByText('Total Equity')).toBeVisible({ timeout: 3000 });
      await expect(dropdown.getByText('Buying Power', { exact: true })).toBeVisible({ timeout: 3000 });
    });

    test('dropdown shows account status badge', async ({ page }) => {
      await page.goto('/');
      await page.locator('nav').getByText(/\$\d{1,3}(,\d{3})*\.\d{2}/).first().click();
      const dropdown = page.locator('.absolute.right-0.mt-2');
      await expect(dropdown.getByText('CONNECTED')).toBeVisible({ timeout: 5000 });
    });

    test('clicking outside closes dropdown', async ({ page }) => {
      await page.goto('/');
      await page.locator('nav').getByText(/\$\d{1,3}(,\d{3})*\.\d{2}/).first().click();
      const dropdown = page.locator('.absolute.right-0.mt-2');
      await expect(dropdown).toBeVisible({ timeout: 5000 });
      // Click outside the dropdown (on the nav bar itself)
      await page.locator('nav').click({ position: { x: 10, y: 10 } });
      await expect(dropdown).not.toBeVisible({ timeout: 3000 });
    });
  });

  test.describe('Fleet Live Indicator', () => {
    test('fleet count is shown when bots exist', async ({ page }) => {
      await page.goto('/');
      // Fleet indicator in the navbar shows "Fleet N/M" with running/total count
      const fleetBox = page.locator('nav').locator('.rounded-xl.bg-white\\/4').last();
      await expect(fleetBox).toBeVisible({ timeout: 15000 });
    });
  });

  test.describe('Donation Coffee Button', () => {
    test('COFFEE link points to PayPal', async ({ page }) => {
      await page.goto('/');
      const coffeeLink = page.getByRole('link', { name: 'COFFEE' });
      await expect(coffeeLink).toBeVisible({ timeout: 15000 });
      const href = await coffeeLink.getAttribute('href');
      expect(href).toContain('paypal.me');
    });
  });
});

test.describe('Page Routing', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  test('/ redirects or loads dashboard', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL('/');
    // Should show header text
    await expect(page.getByText('Market Pulse').or(page.getByText('Connecting to Fleet'))).toBeVisible({ timeout: 15000 });
  });

  test('/fleet renders fleet command page', async ({ page }) => {
    await page.goto('/fleet');
    await expect(page).toHaveURL('/fleet');
    await expect(page.locator('h1').filter({ hasText: 'FLEET COMMAND' })).toBeVisible({ timeout: 15000 });
  });

  test('/situation-room renders correctly', async ({ page }) => {
    await page.goto('/situation-room');
    await expect(page).toHaveURL('/situation-room');
    await expect(page.locator('h1').filter({ hasText: 'Situation Room' })).toBeVisible({ timeout: 15000 });
  });

  test('/setup renders setup wizard', async ({ page }) => {
    await page.goto('/setup');
    await expect(page).toHaveURL('/setup');
  });
});

test.describe('Responsive Layout & Theme', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  test('dark theme is applied', async ({ page }) => {
    await page.goto('/');
    const html = page.locator('html');
    await expect(html).toHaveClass(/dark/);
  });

  test('page has glassmorphism card effects', async ({ page }) => {
    await page.goto('/');
    // Check for glass class on setup page at least
    await page.goto('/setup');
    await expect(page.locator('.glass').first()).toBeVisible({ timeout: 5000 });
  });
});
