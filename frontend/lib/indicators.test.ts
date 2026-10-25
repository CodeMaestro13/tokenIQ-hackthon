import { describe, it, expect } from 'vitest';
import { ema } from './indicators';
describe('chart EMA parity', () => {
  it('seeds with the same SMA as the backend', () => {
    const candles = [1, 2, 3, 4].map((close, time) => ({
      time,
      close,
      open: close,
      high: close,
      low: close,
      volume: 1,
    }));
    expect(ema(candles, 3)).toEqual([
      { time: 2, value: 2 },
      { time: 3, value: 3 },
    ]);
  });
  it('does not fabricate warm-up values', () => {
    expect(ema([], 20)).toEqual([]);
  });
});
