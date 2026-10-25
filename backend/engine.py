import asyncio
import math
import os
import time
import uuid
from datetime import datetime, timezone
from .schemas import StrategyConfig, RiskConfig
from .storage import Storage
from .strategy import evaluate, ema
from .risk_manager import validate
from .delta_client import DeltaClient


def now():
    return datetime.now(timezone.utc).isoformat()


class Engine:
    def __init__(self, path=None, mode=None):
        self.mode = mode or os.getenv('ALGOLENS_MODE', 'demo')
        if self.mode not in ('demo', 'testnet'):
            raise ValueError('ALGOLENS_MODE must be demo or testnet')
        self.storage = Storage(path or os.getenv('ALGOLENS_DB', f'algolens-{self.mode}.db'))
        stored_mode = self.storage.get('metadata', 'mode')
        if stored_mode is not None and stored_mode != self.mode:
            self.storage.db.close()
            raise ValueError('Database belongs to another mode. Use a separate database for Demo and Testnet.')
        self.storage.put('metadata', 'mode', self.mode)
        self.config = StrategyConfig(**self.storage.get('config', 'strategy', {}))
        self.risk = RiskConfig(**self.storage.get('config', 'risk', {}))
        self.status = 'STOPPED'
        self.events = self.storage.all('event')[-500:]
        self.sequence = max([e['sequence'] for e in self.events], default=0)
        self.decisions = self.storage.all('decision')
        self.orders = self.storage.all('order')
        self.position = self.storage.get('state', 'position') if self.mode == 'demo' else None
        self.realized = self.storage.get('state', 'realized', 0) if self.mode == 'demo' else 0
        self.session_realized_start = self.realized
        self.loss_day = datetime.now(timezone.utc).date().isoformat()
        self.daily_loss = self.storage.get('loss', self.loss_day, 0)
        self.candles = []
        self.clients = set()
        self.lock = asyncio.Lock()
        self.delta = DeltaClient()
        self.last_update = None
        self.exchange_connected = False
        self.error = None
        self.step = 0
        self.reconciled = False
        if self.mode == 'demo':
            seconds = {'1m': 60, '5m': 300, '15m': 900}[self.config.timeframe]
            base = int(time.time()) // seconds * seconds - 120 * seconds
            for i in range(120):
                self.candles.append(self.demo_candle(base + i * seconds, i))
            self.step = 120
            saved_market = self.storage.get('state', 'market')
            if saved_market:
                self.candles, self.step = saved_market['candles'], saved_market['step']
            self.last_update = now()
        self.emit('system_status', {'message': 'Backend ready. Strategy requires explicit start after restart.'})

    def emit(self, kind, payload, correlation=None, severity='INFO'):
        self.sequence += 1
        event = {'event_id': uuid.uuid4().hex, 'sequence': self.sequence, 'type': kind,
                 'timestamp': now(), 'correlation_id': correlation or uuid.uuid4().hex,
                 'severity': severity, 'mode': self.mode, 'payload': payload}
        self.storage.put('event', str(self.sequence), event)
        self.events = (self.events + [event])[-500:]
        for queue in list(self.clients):
            if queue.full():
                # A gap forces clients to recover a REST snapshot.
                queue.get_nowait()
            queue.put_nowait(event)
        return event

    def demo_candle(self, timestamp, index):
        def price(i):
            return round(67400 + 430 * math.sin(i / 13) + 65 * math.sin(i / 4), 2)
        opening, closing = price(index - 1), price(index)
        return {'time': timestamp, 'open': opening, 'high': max(opening, closing) + 24,
                'low': min(opening, closing) - 24, 'close': closing, 'volume': 8 + index % 9}

    def account(self):
        if self.mode != 'demo':
            return None
        price = self.candles[-1]['close']
        unrealized = self.pnl(price)
        equity = 10000 + self.realized + unrealized
        exposure = abs(self.position['quantity'] * 0.001 * price) if self.position else 0
        return {'equity': equity, 'available_margin': equity - exposure, 'unrealized_pnl': unrealized,
                'realized_pnl': self.realized - self.session_realized_start, 'daily_loss': self.daily_loss,
                'exposure': exposure, 'currency': 'USD', 'active_positions': int(self.position is not None)}

    def pnl(self, price):
        if not self.position:
            return 0
        p = self.position
        return (price - p['entry_price']) * p['quantity'] * 0.001 * (1 if p['side'] == 'BUY' else -1)

    def positions(self):
        if not self.position:
            return []
        return [{**self.position, 'mark_price': self.candles[-1]['close'], 'unrealized_pnl': self.pnl(self.candles[-1]['close'])}]

    def snapshot(self):
        return {'mode': self.mode, 'as_of': now(), 'last_update': self.last_update, 'sequence': self.sequence,
                'status': self.status, 'config': self.config.model_dump(), 'risk_config': self.risk.model_dump(),
                'account': self.account(), 'positions': self.positions(), 'orders': self.orders[-200:][::-1],
                'events': self.events[-150:][::-1], 'decisions': self.decisions[-100:][::-1],
                'candles': self.candles[-300:], 'exchange_connected': self.exchange_connected,
                'error': self.error, 'execution_enabled': self.mode == 'demo',
                'warming_up': len(self.candles) < self.config.slow_period + 1}

    async def start(self):
        async with self.lock:
            if self.status == 'RUNNING':
                return
            if self.mode != 'demo':
                raise ValueError('Testnet execution locked: account region, contract sizing, native protection and reconciliation require verification. Read-only connection is available.')
            if not self.risk.confirmed:
                raise ValueError('Save and confirm risk limits before starting')
            if self.config.quantity > self.risk.max_quantity:
                raise ValueError('Position size exceeds maximum quantity')
            self.session_realized_start = self.realized
            self.status = 'RUNNING'
            self.emit('strategy_status', {'status': self.status, 'message': 'EMA Crossover started'})

    async def stop(self, emergency=False):
        async with self.lock:
            self.status = 'STOPPED'
            # Demo fills are synchronous; there are no pending entry orders to cancel.
            self.emit('strategy_status', {'status': self.status, 'message':
                ('Emergency stop: entry automation disabled; protective exits retained.' if emergency else
                 'Strategy stopped. Open positions remain monitored and protected.')})

    def close_position(self, price, correlation, reason):
        p = self.position
        if not p:
            return
        pnl = self.pnl(price)
        self.realized += pnl
        self.daily_loss += max(0, -pnl)
        self.storage.put('loss', self.loss_day, self.daily_loss)
        self.storage.put('state', 'realized', self.realized)
        self.fill('SELL' if p['side'] == 'BUY' else 'BUY', p['quantity'], price, correlation, True, reason)
        self.position = None
        self.storage.put('state', 'position', None)
        self.emit('position_update', {'message': reason, 'realized_pnl': pnl, 'positions': []}, correlation)

    def fill(self, side, quantity, price, correlation, reduce_only=False, reason='EMA crossover'):
        order = {'id': 'demo_' + uuid.uuid4().hex[:12], 'symbol': self.config.symbol, 'side': side,
                 'quantity': quantity, 'filled_quantity': 0, 'average_fill_price': None,
                 'type': 'MARKET', 'status': 'SUBMITTED', 'timestamp': now(),
                 'correlation_id': correlation, 'reduce_only': reduce_only, 'reason': reason, 'mode': self.mode}
        self.orders.append(order)
        for state in ['SUBMITTED', 'ACKNOWLEDGED', 'FILLED']:
            order['status'] = state
            if state == 'FILLED':
                order.update(filled_quantity=quantity, average_fill_price=price)
            self.storage.put('order', order['id'], order)
            self.emit('order_update', dict(order), correlation)
        return order

    async def tick(self):
        async with self.lock:
            day = datetime.now(timezone.utc).date().isoformat()
            if day != self.loss_day:
                self.loss_day, self.daily_loss = day, self.storage.get('loss', day, 0)
            seconds = {'1m': 60, '5m': 300, '15m': 900}[self.config.timeframe]
            candle = self.demo_candle(self.candles[-1]['time'] + seconds, self.step)
            self.step += 1
            self.candles = (self.candles + [candle])[-500:]
            self.storage.put('state', 'market', {'candles': self.candles, 'step': self.step})
            self.last_update = now()
            self.emit('candle_update', {'candle': candle, 'message': 'Completed simulated candle (accelerated replay clock)'})
            if self.position:
                p = self.position
                buy = p['side'] == 'BUY'
                stop = candle['low'] <= p['stop_loss'] if buy else candle['high'] >= p['stop_loss']
                take = candle['high'] >= p['take_profit'] if buy else candle['low'] <= p['take_profit']
                # Conservative ordering when both protection levels are touched in a candle.
                if stop or take:
                    self.close_position(p['stop_loss'] if stop else p['take_profit'], uuid.uuid4().hex, 'Stop loss' if stop else 'Take profit')
            if self.status != 'RUNNING':
                return
            result = evaluate(self.candles, self.config)
            if not result or result['side'] == 'HOLD':
                return
            key = f"{self.config.symbol}:{self.config.timeframe}:{candle['time']}"
            if not self.storage.claim(key, result):
                return
            correlation = uuid.uuid4().hex
            side = result['side']
            explanation = f"{side}: EMA {self.config.fast_period} ({result['fast_ema']:.2f}) crossed {'above' if side == 'BUY' else 'below'} EMA {self.config.slow_period} ({result['slow_ema']:.2f}) on the completed {self.config.timeframe} candle."
            decision = {**result, 'id': correlation, 'timestamp': now(), 'symbol': self.config.symbol,
                        'timeframe': self.config.timeframe, 'explanation': explanation,
                        'risk_checks': [], 'order_id': None, 'status': 'NO TRADE'}
            self.emit('signal_generated', decision.copy(), correlation)
            if self.position:
                if self.position['side'] != side:
                    self.close_position(candle['close'], correlation, 'Opposite crossover: reduce-only close')
                    decision['status'] = 'CLOSED'
                    decision['order_id'] = self.orders[-1]['id']
                    decision['risk_checks'] = [{'rule': 'Reduce-only exit', 'status': 'PASSED', 'detail': 'Existing exposure reduced; no new entry'}]
                else:
                    decision['explanation'] += ' Existing same-side position retained.'
            else:
                checks = validate(self.config, self.risk, self.account(), candle['close'], self.position)
                decision['risk_checks'] = checks
                self.emit('risk_evaluation', {'checks': checks, 'message': 'Pre-trade risk evaluation'}, correlation)
                if all(c['status'] == 'PASSED' for c in checks):
                    price = candle['close']
                    direction = 1 if side == 'BUY' else -1
                    order = self.fill(side, self.config.quantity, price, correlation)
                    self.position = {'id': correlation, 'symbol': self.config.symbol, 'side': side,
                                     'quantity': self.config.quantity, 'entry_price': price,
                                     'stop_loss': price * (1 - direction * self.config.stop_loss_pct / 100),
                                     'take_profit': price * (1 + direction * self.config.take_profit_pct / 100),
                                     'updated_at': now(), 'strategy': 'EMA_CROSSOVER', 'protection': 'SIMULATED ACTIVE'}
                    self.storage.put('state', 'position', self.position)
                    self.emit('position_update', {'position': self.position, 'message': 'Simulated protected position opened'}, correlation)
                    decision.update(status='FILLED', order_id=order['id'])
                else:
                    decision['status'] = 'REJECTED'
                    decision['explanation'] += ' Risk rejected: ' + ', '.join(c['rule'] for c in checks if c['status'] == 'FAILED')
            self.decisions.append(decision)
            self.storage.put('decision', correlation, decision)
            self.emit('decision_completed', decision, correlation)

    async def run(self):
        while True:
            try:
                if self.mode == 'demo':
                    await self.tick()
                else:
                    self.candles = await self.delta.candles(self.config.symbol, self.config.timeframe)
                    self.exchange_connected = True
                    self.last_update = now()
                    self.error = None
                    self.emit('market_snapshot', {'message': 'Read-only Testnet candle snapshot updated'})
            except asyncio.CancelledError:
                raise
            except Exception:
                self.exchange_connected = False
                self.error = 'Data update failed. Check exchange configuration and connectivity.'
                self.emit('system_error', {'message': self.error}, severity='ERROR')
            await asyncio.sleep(2 if self.mode == 'demo' else 10)
