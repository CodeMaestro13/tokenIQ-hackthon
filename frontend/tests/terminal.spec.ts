import { test, expect } from '@playwright/test';
test('demo lifecycle and route navigation', async ({ page }) => {
  await page.goto('/risk');
  await expect(page.getByText('SIMULATED DATA — DEMO MODE')).toBeVisible();
  await page.getByRole('button', { name: 'Save risk limits' }).click();
  await expect(page.getByRole('status')).toContainText('confirmed');
  await page.goto('/strategy');
  await page.getByRole('button', { name: 'Start strategy' }).click();
  await expect(page.getByText('● RUNNING')).toBeVisible();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(page.getByText('● STOPPED')).toBeVisible();
  for (const route of ['dashboard', 'trading', 'positions', 'orders', 'logs', 'settings']) {
    await page.goto('/' + route);
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.getByText('SIMULATED DATA — DEMO MODE')).toBeVisible();
  }
});
test('mobile layout contains chart without page overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dashboard');
  await expect(page.getByLabel('Candlestick chart with EMA overlays')).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy();
  await page.screenshot({ path: 'test-results/mobile-dashboard.png', fullPage: true });
});
test('signal inspector exposes real backend evaluation and simulated fill', async ({ page }) => {
  test.setTimeout(110000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/risk');
  await page.getByRole('button', { name: 'Save risk limits' }).click();
  await page.goto('/strategy');
  await page.getByRole('button', { name: 'Start strategy' }).click();
  await page.goto('/dashboard');
  await expect(page.getByRole('button', { name: 'Inspect decision', exact: true })).toBeVisible({
    timeout: 95000,
  });
  await page.screenshot({ path: 'test-results/desktop-dashboard.png', fullPage: true });
  await page.getByRole('button', { name: 'Inspect decision', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Trade Decision Inspector' })).toBeVisible();
  await expect(page.getByText('Previous fast / slow')).toBeVisible();
  await expect(page.getByText('Current fast / slow')).toBeVisible();
  await page.screenshot({ path: 'test-results/decision-inspector.png', fullPage: true });
  await page.getByRole('button', { name: 'Close inspector' }).click();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  expect(errors).toEqual([]);
});
