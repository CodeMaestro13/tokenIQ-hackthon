def ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    current = sum(values[:period]) / period
    result[period - 1] = current
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        current = values[i] * alpha + current * (1 - alpha)
        result[i] = current
    return result


def evaluate(candles, config):
    values = [c['close'] for c in candles]
    fast, slow = ema(values, config.fast_period), ema(values, config.slow_period)
    if len(values) < config.slow_period + 1:
        return None
    side = 'HOLD'
    if fast[-2] <= slow[-2] and fast[-1] > slow[-1]:
        side = 'BUY'
    elif fast[-2] >= slow[-2] and fast[-1] < slow[-1]:
        side = 'SELL'
    return {'side': side, 'fast_ema': fast[-1], 'slow_ema': slow[-1],
            'previous_fast_ema': fast[-2], 'previous_slow_ema': slow[-2],
            'price': values[-1], 'candle_time': candles[-1]['time']}
