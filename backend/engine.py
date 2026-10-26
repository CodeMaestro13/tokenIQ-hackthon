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
from .exchange_data import normalize, connection_error
from .testnet_trader import TestnetTrader
from .trade_results import report


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
        self.session_id = uuid.uuid4().hex
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
        self.account_data = None
        self.exchange_positions = []
        self.account_connected = False
        self.account_error = None
        self.account_updated_at = None
        self.latest_evaluation = None
        self.last_observed_candle = None
        self.trader = TestnetTrader(self) if self.mode == 'testnet' else None
        self.execution_error = None
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
            return self.account_data
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
        if self.mode == 'testnet':
            return self.exchange_positions
        if not self.position:
            return []
        return [{**self.position, 'mark_price': self.candles[-1]['close'], 'unrealized_pnl': self.pnl(self.candles[-1]['close'])}]

    def snapshot(self):
        seconds = {'1m': 60, '5m': 300, '15m': 900}[self.config.timeframe]
        market_stale = self.mode == 'testnet' and (not self.candles or time.time() - (self.candles[-1]['time'] + seconds) > max(30, seconds))
        return {'mode': self.mode, 'session_id': self.session_id, 'as_of': now(), 'last_update': self.last_update, 'sequence': self.sequence,
                'status': self.status, 'config': self.config.model_dump(), 'risk_config': self.risk.model_dump(),
                'account': self.account(), 'positions': self.positions(), 'orders': self.orders[-200:][::-1],
                'events': self.events[-150:][::-1], 'decisions': self.decisions[-100:][::-1],
                'candles': self.candles[-300:], 'exchange_connected': self.exchange_connected,
                'error': self.error, 'execution_enabled': self.mode == 'demo' or bool(self.trader and self.trader.product and self.account_connected and self.delta.host == 'https://cdn-ind.testnet.deltaex.org'),
                'execution_preflight': self.trader.preflight if self.trader else None, 'execution_error': self.execution_error,
                'account_connected': self.account_connected, 'account_error': self.account_error,
                'account_updated_at': self.account_updated_at, 'latest_evaluation': self.latest_evaluation,
                'strategy_monitoring': self.mode == 'testnet' and self.latest_evaluation is not None,
                'market_stale': market_stale,
                'indicators': {'fast': [{'time': c['time'], 'value': v} for c, v in zip(self.candles, ema([c['close'] for c in self.candles], self.config.fast_period)) if v is not None][-300:],
                               'slow': [{'time': c['time'], 'value': v} for c, v in zip(self.candles, ema([c['close'] for c in self.candles], self.config.slow_period)) if v is not None][-300:]},
                'warming_up': len(self.candles) < self.config.slow_period + 1}

    def trade_results(self):
        if self.mode=='demo':
            return report([{**o,'paid_commission':0} for o in self.orders],{self.config.symbol:'0.001'})
        products={p['symbol']:p['contract_value'] for p in self.storage.all('product')}
        if self.trader and self.trader.product:
            products[self.trader.product['symbol']]=self.trader.product['contract_value']
        owned_ids={str(i['order_id']) for i in self.storage.all('live_intent') if i.get('order_id')}
        return report(self.orders,products,owned_ids)

    async def start(self):
        async with self.lock:
            if self.status == 'RUNNING':
                return
            if self.mode == 'testnet':
                await self.refresh_account()
                if not self.account_connected:
                    raise ValueError(self.account_error or 'Authenticate the Testnet account before starting')
                await self.trader.prepare()
                checks = self.trader.update_preflight()
                if not checks['ready']:
                    raise ValueError(checks['reason'])
                if len(self.candles) < self.config.slow_period + 1:
                    raise ValueError('Waiting for enough completed candles')
                self.trader.last_candle = self.candles[-1]['time']
                self.trader.session_start = time.time()
                self.status = 'RUNNING'
                self.execution_error = None
                self.emit('strategy_status', {'status': self.status, 'message': 'Genuine India Testnet automation started. Waiting for a new completed-candle crossover.'})
                return
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
            if self.trader and emergency:
                await self.trader.cancel_entries()
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
            self.latest_evaluation = result
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

    async def refresh_account(self):
        try:
            wallet, positions, orders = await self.delta.account_snapshot()
            updated = now()
            self.account_data, self.exchange_positions, self.orders = normalize(wallet, positions, orders, updated)
            owned = {o['id']: o for o in self.storage.all('order') if o.get('mode') == 'testnet'}
            self.orders = [{**o, 'correlation_id': owned[o['id']]['correlation_id'], 'reason': owned[o['id']]['reason']} if o['id'] in owned else o for o in self.orders]
            present = {o['id'] for o in self.orders}
            self.orders = sorted([*self.orders, *[o for key, o in owned.items() if key not in present]], key=lambda o: o['timestamp'])
            self.account_connected = True
            self.account_updated_at = updated
            self.account_error = None if self.account_data else 'Authenticated, but no USD wallet was returned. USD summary metrics are unavailable.'
            self.emit('account_update', {'message': 'Authenticated exchange snapshot refreshed (read-only)'})
        except Exception as exc:
            message = connection_error(exc)
            changed = message != self.account_error
            self.account_connected = False
            self.account_error = message
            if changed:
                self.emit('account_error', {'message': message}, severity='WARNING')

    async def testnet_cycle(self):
        async with self.lock:
            self.candles = await self.delta.candles(self.config.symbol, self.config.timeframe)
            self.exchange_connected = True
            self.last_update = now()
            self.error = None
            await self.refresh_account()
            if self.account_connected:
                try:
                    if not self.trader.product or self.trader.product['symbol'] != self.config.symbol:
                        await self.trader.prepare()
                    else:
                        await self.trader.refresh_ledger()
                        await self.trader.reconcile()
                    await self.enrich_positions()
                    self.trader.update_preflight()
                    if self.status != 'ERROR':
                        self.execution_error = None
                except Exception as exc:
                    self.execution_error = str(exc) if isinstance(exc, ValueError) else 'Execution reconciliation failed; entries blocked'
                    if self.status == 'RUNNING':
                        self.status = 'ERROR'
                    self.trader.preflight = {'ready': False, 'checks': [], 'reason': self.execution_error}
            elif self.status == 'RUNNING':
                self.status = 'ERROR'
                self.execution_error = self.account_error
            self.observe_strategy()
            self.emit('market_snapshot', {'message': 'Testnet market and account snapshot refreshed'})
            if self.status == 'RUNNING' and not self.execution_error:
                await self.execute_testnet_signal()

    async def enrich_positions(self):
        if not self.account_data or not self.trader.product:
            return
        product = self.trader.product
        exposure, unrealized = 0, 0
        known = True
        for position in self.exchange_positions:
            if position['symbol'] != product['symbol']:
                known = False
                continue
            if position['mark_price'] is None:
                ticker = await self.delta.request('/v2/tickers/' + product['symbol'])
                position['mark_price'] = float(ticker['mark_price'])
            multiplier = float(product['contract_value'])
            exposure += position['quantity'] * multiplier * position['mark_price']
            if position['unrealized_pnl'] is None and position['entry_price'] is not None:
                position['unrealized_pnl'] = (position['mark_price'] - position['entry_price']) * position['quantity'] * multiplier * (1 if position['side'] == 'BUY' else -1)
            if position['unrealized_pnl'] is None:
                known = False
            else:
                unrealized += position['unrealized_pnl']
            owned = next((i for i in self.storage.all('live_intent') if i['product_id'] == product['id'] and i['state'] == 'PROTECTED' and i['purpose'] == 'EMA crossover entry'), None)
            if owned:
                position.update(stop_loss=owned['stop_loss'], take_profit=owned['take_profit'], protection='EXCHANGE ACTIVE', strategy='EMA_CROSSOVER')
        self.account_data['exposure'] = exposure if known else None
        self.account_data['unrealized_pnl'] = unrealized if known else None
        if known and self.account_data.get('wallet_balance') is not None:
            self.account_data['equity'] = self.account_data['wallet_balance'] + unrealized

    async def execute_testnet_signal(self):
        if self.status != 'RUNNING':
            return
        result = evaluate(self.candles, self.config)
        if not result or result['candle_time'] == self.trader.last_candle:
            return
        self.trader.last_candle = result['candle_time']
        if result['side'] == 'HOLD':
            return
        key = f"trade:{self.config.symbol}:{self.config.timeframe}:{result['candle_time']}"
        if not self.storage.claim(key, result):
            return
        correlation = uuid.uuid4().hex
        decision = {**result, 'id': correlation, 'timestamp': now(), 'symbol': self.config.symbol,
                    'timeframe': self.config.timeframe, 'order_id': None, 'status': 'EVALUATING',
                    'explanation': f"{result['side']}: EMA {self.config.fast_period} ({result['fast_ema']:.4f}) crossed {'above' if result['side']=='BUY' else 'below'} EMA {self.config.slow_period} ({result['slow_ema']:.4f}) on a completed {self.config.timeframe} candle.",
                    'risk_checks': []}
        self.storage.put('decision', correlation, decision)
        self.emit('signal_generated', decision.copy(), correlation)
        try:
            if self.exchange_positions:
                if len(self.exchange_positions) == 1 and self.exchange_positions[0]['symbol'] == self.config.symbol and self.exchange_positions[0]['side'] != result['side']:
                    decision['risk_checks'] = [{'rule': 'Reduce-only exit', 'status': 'PASSED', 'detail': 'Only the owned protected strategy position may be closed'}]
                    await self.trader.close_opposite(decision)
                else:
                    decision.update(status='NO TRADE', explanation=decision['explanation']+' Existing exposure retained; no additional entry.')
            else:
                decision['risk_checks'] = self.trader.checks(result['price'])
                self.emit('risk_evaluation', {'checks': decision['risk_checks']}, correlation)
                if all(c['status'] == 'PASSED' for c in decision['risk_checks']):
                    await self.trader.execute(decision)
                else:
                    decision['status'] = 'REJECTED'
                    decision['explanation'] += ' Risk rejected: '+', '.join(c['rule'] for c in decision['risk_checks'] if c['status']=='FAILED')
        except Exception as exc:
            decision['status'] = 'ERROR'
            self.status = 'ERROR'
            self.execution_error = str(exc) if isinstance(exc, ValueError) else 'Exchange execution error. Inspect persisted order intents before restarting.'
            decision['explanation'] += ' '+self.execution_error
            self.emit('system_error', {'message': self.execution_error}, correlation, 'ERROR')
        self.storage.put('decision', correlation, decision)
        self.decisions = self.storage.all('decision')
        self.emit('decision_completed', decision, correlation)

    def observe_strategy(self):
        self.latest_evaluation = evaluate(self.candles, self.config)
        if not self.latest_evaluation:
            return
        result = self.latest_evaluation
        candle_key = (self.config.symbol, self.config.timeframe, self.config.fast_period,
                      self.config.slow_period, result['candle_time'])
        if candle_key == self.last_observed_candle:
            return
        self.last_observed_candle = candle_key
        self.emit('indicator_calculated', {'message': f"Read-only evaluation: {result['side']}", **result})
        if result['side'] == 'HOLD':
            return
        if self.status == 'RUNNING':
            return
        key = 'observe:' + ':'.join(map(str, candle_key))
        if not self.storage.claim(key, result):
            return
        side = result['side']
        correlation = uuid.uuid4().hex
        decision = {**result, 'id': correlation, 'timestamp': now(), 'symbol': self.config.symbol,
                    'timeframe': self.config.timeframe, 'status': 'OBSERVED', 'order_id': None,
                    'explanation': f"{side}: EMA {self.config.fast_period} ({result['fast_ema']:.2f}) crossed {'above' if side == 'BUY' else 'below'} EMA {self.config.slow_period} ({result['slow_ema']:.2f}) on the completed {self.config.timeframe} candle. Observed in read-only mode; no order requested.",
                    'risk_checks': [{'rule': rule, 'status': 'NOT EVALUATED', 'detail': 'Read-only observation; no order requested.'}
                                    for rule in ('Position size', 'Exposure', 'Available margin', 'Daily loss', 'Duplicate prevention', 'Stop-loss policy')]}
        self.decisions.append(decision)
        self.storage.put('decision', correlation, decision)
        self.emit('signal_observed', decision, correlation)

    async def run(self):
        while True:
            try:
                if self.mode == 'demo':
                    await self.tick()
                else:
                    await self.testnet_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.exchange_connected = False
                self.error = 'Data update failed. Check exchange configuration and connectivity.'
                self.emit('system_error', {'message': self.error}, severity='ERROR')
            await asyncio.sleep(2 if self.mode == 'demo' else 10)
