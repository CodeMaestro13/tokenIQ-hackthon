import type { Candle } from './types';
export function ema(candles: Candle[], period: number) {
  if (candles.length < period) return [];
  let value = candles.slice(0, period).reduce((s, c) => s + c.close, 0) / period;
  const points = [{ time: candles[period - 1].time, value }];
  for (let i = period; i < candles.length; i++) {
    value = (candles[i].close * 2) / (period + 1) + value * (1 - 2 / (period + 1));
    points.push({ time: candles[i].time, value });
  }
  return points;
}
