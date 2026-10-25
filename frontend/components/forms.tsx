'use client';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import type { Snapshot, Config, Risk } from '@/lib/types';
import { Button } from './ui/button';
const schema = z
  .object({
    symbol: z.string().min(1),
    timeframe: z.enum(['1m', '5m', '15m']),
    fast_period: z.number().int().min(2).max(100),
    slow_period: z.number().int().min(3).max(200),
    quantity: z.number().int().min(1).max(100),
    stop_loss_pct: z.number().positive().max(20),
    take_profit_pct: z.number().positive().max(50),
  })
  .refine((v) => v.fast_period < v.slow_period, {
    path: ['fast_period'],
    message: 'Fast EMA must be smaller than slow EMA',
  });
export function StrategyForm({
  data,
  save,
  busy,
}: {
  data: Snapshot;
  save: (c: Config) => Promise<void>;
  busy: boolean;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Config>({ resolver: zodResolver(schema), defaultValues: data.config });
  return (
    <form onSubmit={handleSubmit(save)} className="form-grid">
      <label>
        Trading instrument
        <select {...register('symbol')}>
          <option>{data.config.symbol}</option>
        </select>
      </label>
      <label>
        Candle timeframe
        <select {...register('timeframe')}>
          <option value="1m">1 minute</option>
          <option value="5m">5 minutes</option>
          <option value="15m">15 minutes</option>
        </select>
      </label>
      {(
        [
          ['fast_period', 'Fast EMA period'],
          ['slow_period', 'Slow EMA period'],
          ['quantity', 'Position size · contracts'],
          ['stop_loss_pct', 'Stop loss · %'],
          ['take_profit_pct', 'Take profit · %'],
        ] as const
      ).map(([key, label]) => (
        <label key={key}>
          {label}
          <input
            type="number"
            step={key.includes('pct') ? '0.1' : '1'}
            {...register(key, { valueAsNumber: true })}
          />
          {errors[key] && <small className="negative">{errors[key]?.message}</small>}
        </label>
      ))}
      <div className="form-foot">
        <p>Configuration changes require a stopped strategy and no open position.</p>
        <Button
          type="submit"
          disabled={busy || data.status === 'RUNNING' || data.positions.length > 0}
        >
          Save configuration
        </Button>
      </div>
    </form>
  );
}
export function RiskForm({
  data,
  save,
  busy,
}: {
  data: Snapshot;
  save: (c: Risk) => Promise<void>;
  busy: boolean;
}) {
  const { register, handleSubmit } = useForm<Risk>({
    defaultValues: { ...data.risk_config, confirmed: true },
  });
  return (
    <form onSubmit={handleSubmit(save)} className="form-grid">
      <label>
        Maximum account exposure · %
        <input
          type="number"
          min="0.1"
          max="100"
          step="0.1"
          required
          {...register('max_exposure_pct', { valueAsNumber: true })}
        />
      </label>
      <label>
        Daily realized loss limit · USD
        <input
          type="number"
          min="0.01"
          max="10000"
          step="0.01"
          required
          {...register('daily_loss_limit', { valueAsNumber: true })}
        />
      </label>
      <label>
        Maximum position · contracts
        <input
          type="number"
          min="1"
          max="100"
          required
          {...register('max_quantity', { valueAsNumber: true })}
        />
      </label>
      <div className="form-foot">
        <p>Saving confirms these limits. Risk checks run on the server before every entry.</p>
        <Button disabled={busy || data.status === 'RUNNING'}>Save risk limits</Button>
      </div>
    </form>
  );
}
