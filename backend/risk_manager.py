def validate(config, limits, account, price, position, duplicate=False):
    notional = config.quantity * 0.001 * price
    checks = [
        ('Position size', config.quantity <= limits.max_quantity, f'{config.quantity} / {limits.max_quantity} contracts'),
        ('Exposure', notional <= account['equity'] * limits.max_exposure_pct / 100, f'${notional:.2f} / {limits.max_exposure_pct}% equity'),
        ('Available margin', notional <= account['available_margin'], 'Conservative fully collateralized entry'),
        ('Daily loss', account['daily_loss'] < limits.daily_loss_limit, f"${account['daily_loss']:.2f} / ${limits.daily_loss_limit:.2f}"),
        ('Duplicate prevention', not duplicate, 'Unique completed-candle intent'),
        ('Stop-loss policy', config.stop_loss_pct > 0 and config.take_profit_pct > 0, 'Stop-loss and take-profit required'),
        ('Risk configuration', limits.confirmed, 'Operator must save risk limits'),
    ]
    return [{'rule': name, 'status': 'PASSED' if passed else 'FAILED', 'detail': detail} for name, passed, detail in checks]
