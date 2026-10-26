import { test, expect } from '@playwright/test';
test('judges can distinguish gross profit, commissions and net loss', async ({ page }) => {
  const report = {
    mode: 'testnet',
    as_of: new Date().toISOString(),
    account_connected: true,
    account_error: null,
    closed_count: 1,
    gross_pnl: 0.04,
    fees: 0.08538216,
    net_pnl: -0.04538216,
    warnings: [],
    scope: 'AlgoLens closed trades',
    trades: [
      {
        id: 'entry:exit:0',
        symbol: 'BTCUSD',
        side: 'LONG',
        quantity: 1,
        contract_value: 0.001,
        base_quantity: 0.001,
        entry_price: 80377.5,
        exit_price: 80417.5,
        gross_pnl: 0.04,
        fees: 0.08538216,
        net_pnl: -0.04538216,
        entry_order_id: '2176312308',
        exit_order_id: '2176318892',
        closed_at: '2026-10-25T12:22:31Z',
        mode: 'testnet',
      },
    ],
  };
  await page.route('**/api/trade-results', (route) => route.fulfill({ json: report }));
  await page.goto('/dashboard');
  await expect(page.getByTestId('gross-trade-pnl')).toHaveText('+$0.0400');
  await expect(page.getByTestId('trade-fees')).toHaveText('$0.08538216');
  await expect(page.getByTestId('net-trade-pnl')).toHaveText('-$0.04538216');
  await expect(page.getByTestId('net-trade-pnl')).toHaveClass(/negative/);
  await expect(page.getByText('$80,377.50', { exact: true })).toBeVisible();
  await page
    .locator('section[aria-label="Closed trade results"]')
    .screenshot({ path: 'test-results/closed-trade-results.png' });
  await page.goto('/orders');
  await expect(page.getByTestId('gross-trade-pnl')).toHaveText('+$0.0400');
});
