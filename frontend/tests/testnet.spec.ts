import { test, expect } from '@playwright/test';
import type { Snapshot } from '../lib/types';

function snapshot(): Snapshot {
  const time = Math.floor(Date.now() / 60000) * 60 - 60;
  return {
    session_id: 'testnet-session',
    mode: 'testnet',
    as_of: new Date().toISOString(),
    last_update: new Date().toISOString(),
    sequence: 900,
    status: 'STOPPED',
    config: {
      symbol: 'BTCUSD',
      timeframe: '1m',
      fast_period: 20,
      slow_period: 50,
      quantity: 1,
      stop_loss_pct: 1,
      take_profit_pct: 2,
    },
    risk_config: {
      max_exposure_pct: 20,
      daily_loss_limit: 100,
      max_quantity: 10,
      confirmed: false,
    },
    account: null,
    positions: [],
    orders: [],
    events: [],
    decisions: [],
    candles: Array.from({ length: 60 }, (_, i) => ({
      time: time - (59 - i) * 60,
      open: 67000 + i,
      high: 67002 + i,
      low: 66999 + i,
      close: 67001 + i,
      volume: 10,
    })),
    exchange_connected: true,
    error: null,
    execution_enabled: false,
    warming_up: false,
    account_connected: false,
    account_error:
      "Delta rejected account access: this computer's public IP is not whitelisted for the API key.",
    account_updated_at: null,
    strategy_monitoring: true,
    latest_evaluation: {
      side: 'HOLD',
      fast_ema: 67050,
      slow_ema: 67030,
      previous_fast_ema: 67049,
      previous_slow_ema: 67029,
      price: 67060,
      candle_time: time,
    },
  };
}

test('read-only market monitoring clearly separates failed account authentication', async ({
  page,
}) => {
  const data = snapshot();
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/api/snapshot', (route) =>
    route.fulfill({ json: { ...data, as_of: new Date().toISOString() } }),
  );
  await page.goto('/dashboard');
  await expect(page.getByText(/public IP is not whitelisted/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Execution unavailable' })).toBeDisabled();
  await expect(page.getByText('HOLD · READ-ONLY')).toBeVisible();
  await expect(page.getByText('67050.0000', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/testnet-auth-blocked.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('new backend session with a lower sequence replaces the old cached snapshot', async ({
  page,
}) => {
  const data = snapshot();
  await page.route('**/api/snapshot', (route) =>
    route.fulfill({ json: { ...data, as_of: new Date().toISOString() } }),
  );
  await page.goto('/dashboard');
  await expect(page.getByText(/public IP is not whitelisted/)).toBeVisible();
  data.session_id = 'restarted';
  data.sequence = 1;
  data.account_connected = true;
  data.account_error = null;
  data.account_updated_at = new Date().toISOString();
  data.account = {
    equity: 500,
    available_margin: 450,
    unrealized_pnl: null,
    realized_pnl: null,
    daily_loss: null,
    exposure: null,
    currency: 'USD',
    active_positions: 0,
  };
  await expect(page.getByText('$500.00', { exact: true })).toBeVisible({ timeout: 20000 });
  await expect(page.getByText('Account access: authenticated.')).toBeVisible();
});

test('enabled execution reports failing exposure preflight without claiming the bot started', async ({
  page,
}) => {
  const data = snapshot();
  data.account_connected = true;
  data.account_error = null;
  data.execution_enabled = true;
  data.account = {
    equity: 100,
    available_margin: 100,
    unrealized_pnl: 0,
    realized_pnl: null,
    daily_loss: 0,
    exposure: 0,
    currency: 'USD',
    active_positions: 0,
  };
  data.execution_preflight = {
    ready: false,
    checks: [{ rule: 'Exposure', status: 'FAILED', detail: 'Requested $81.84; cap $20' }],
    reason: 'Exposure: requested $81.84 exceeds the configured $20 cap',
  };
  await page.route('**/api/snapshot', (route) =>
    route.fulfill({ json: { ...data, as_of: new Date().toISOString() } }),
  );
  await page.route('**/api/strategy/start', (route) =>
    route.fulfill({
      status: 409,
      json: {
        code: 'ACTION_REJECTED',
        message: 'Exposure: requested $81.84 exceeds the configured $20 cap',
      },
    }),
  );
  await page.goto('/strategy');
  await expect(page.getByText('START BLOCKED')).toBeVisible();
  await page.getByRole('button', { name: 'Start strategy' }).click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Exposure: requested $81.84' }),
  ).toBeVisible();
  await expect(page.getByText('● STOPPED', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/testnet-preflight.png', fullPage: true });
});
