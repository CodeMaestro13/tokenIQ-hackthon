from typing import Literal
from pydantic import BaseModel, Field, model_validator


class StrategyConfig(BaseModel):
    symbol: str = Field(default='BTCUSD', pattern=r'^[A-Z0-9_]{2,30}$')
    timeframe: Literal['1m', '5m', '15m'] = '1m'
    fast_period: int = Field(default=20, ge=2, le=100)
    slow_period: int = Field(default=50, ge=3, le=200)
    quantity: int = Field(default=1, ge=1, le=100)
    stop_loss_pct: float = Field(default=1, gt=0, le=20)
    take_profit_pct: float = Field(default=2, gt=0, le=50)

    @model_validator(mode='after')
    def periods(self):
        if self.fast_period >= self.slow_period:
            raise ValueError('Fast EMA must be smaller than slow EMA')
        return self


class RiskConfig(BaseModel):
    max_exposure_pct: float = Field(default=20, gt=0, le=100)
    daily_loss_limit: float = Field(default=100, gt=0, le=10000)
    max_quantity: int = Field(default=10, ge=1, le=100)
    confirmed: bool = False


class Event(BaseModel):
    event_id: str
    sequence: int
    type: str
    timestamp: str
    correlation_id: str
    severity: str = 'INFO'
    mode: str
    payload: dict
