import type { components } from './api.generated';
export type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};
export type Config = Required<components['schemas']['StrategyConfig']>;
export type Risk = Required<components['schemas']['RiskConfig']>;
export type Account = {
  equity: number | null;
  available_margin: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  daily_loss: number | null;
  exposure: number | null;
  currency: string;
  active_positions: number;
};
export type Position = {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number | null;
  mark_price: number | null;
  unrealized_pnl: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  updated_at: string;
  strategy: string;
  protection: string;
};
export type Order = {
  id: string;
  symbol: string;
  side: string;
  quantity: number | null;
  filled_quantity: number | null;
  average_fill_price: number | null;
  type: string;
  status: string;
  timestamp: string;
  correlation_id: string;
  reduce_only: boolean;
  reason: string;
  mode: string;
};
export type Check = { rule: string; status: string; detail: string };
export type Decision = {
  id: string;
  timestamp: string;
  symbol: string;
  timeframe: string;
  side: string;
  fast_ema: number;
  slow_ema: number;
  previous_fast_ema: number;
  previous_slow_ema: number;
  price: number;
  candle_time: number;
  explanation: string;
  risk_checks: Check[];
  order_id: string | null;
  status: string;
};
export type TradingEvent = {
  event_id: string;
  sequence: number;
  type: string;
  timestamp: string;
  correlation_id: string;
  severity: string;
  mode: string;
  payload: Record<string, unknown>;
};
export type Snapshot = {
  session_id: string;
  market_stale?: boolean;
  indicators?: { fast: { time: number; value: number }[]; slow: { time: number; value: number }[] };
  mode: 'demo' | 'testnet';
  as_of: string;
  last_update: string | null;
  sequence: number;
  status: string;
  config: Config;
  risk_config: Risk;
  account: Account | null;
  positions: Position[];
  orders: Order[];
  events: TradingEvent[];
  decisions: Decision[];
  candles: Candle[];
  exchange_connected: boolean;
  error: string | null;
  execution_enabled: boolean;
  execution_preflight?: { ready: boolean; checks: Check[]; reason: string } | null;
  execution_error?: string | null;
  warming_up: boolean;
  account_connected: boolean;
  account_error: string | null;
  account_updated_at: string | null;
  strategy_monitoring: boolean;
  latest_evaluation: Pick<
    Decision,
    | 'side'
    | 'fast_ema'
    | 'slow_ema'
    | 'previous_fast_ema'
    | 'previous_slow_ema'
    | 'price'
    | 'candle_time'
  > | null;
};
