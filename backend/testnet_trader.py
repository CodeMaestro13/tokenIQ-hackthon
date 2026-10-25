"""Single-position Testnet execution with persisted intents and exchange-native exits.

No POST is retried. Ambiguous submissions are recovered by client_order_id.
Separate reduce-only stop-market exits are used because this Testnet product
advertises show_bracket_orders=false. Protection failures trigger reduce-only flattening.
"""
import asyncio
import hashlib
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import httpx
from .exchange_data import number, timestamp


TERMINAL = {'closed', 'cancelled', 'rejected'}
DEBITS = {'cashflow', 'commission', 'funding', 'settlement', 'liquidation_fee', 'spot_trade'}


class TestnetTrader:
    def __init__(self, engine):
        self.e = engine
        self.product = None
        self.ledger = []
        self.ledger_error = 'Trading ledger has not been reconciled'
        self.session_start = None
        self.last_candle = None
        self.inflight = False
        self.preflight = {'ready': False, 'checks': [], 'reason': 'Preparing exchange execution checks'}

    async def prepare(self):
        self.e.delta.require_trading_host()
        self.product = await self.e.delta.request('/v2/products/' + self.e.config.symbol)
        p = self.product
        if not (p.get('state') == 'live' and p.get('contract_type') == 'perpetual_futures'
                and p.get('notional_type') == 'vanilla' and (p.get('settling_asset') or {}).get('symbol') == 'USD'
                and (p.get('quoting_asset') or {}).get('symbol') == 'USD'
                and (number(p.get('contract_value')) or 0) > 0 and (number(p.get('tick_size')) or 0) > 0):
            raise ValueError('Execution supports live USD-quoted, USD-settled linear perpetual contracts only')
        await self.refresh_ledger()
        await self.reconcile()

    async def refresh_ledger(self):
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = min(today.timestamp(), self.session_start or today.timestamp())
        try:
            self.ledger = await self.e.delta.pages('/v2/wallet/transactions', {
                'asset_ids': self.product['settling_asset']['id'], 'start_time': int(start * 1_000_000)})
            self.ledger_error = None
            if self.e.account_data:
                entries = []
                for row in self.ledger:
                    if row.get('transaction_type') not in DEBITS:
                        continue
                    amount = number(row.get('amount'))
                    stamp = timestamp(row.get('created_at'))
                    if amount is None or stamp is None:
                        raise ValueError('Incomplete exchange ledger entry')
                    entries.append((datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp(), amount))
                self.e.account_data['daily_loss'] = sum(max(0, -amount) for stamp, amount in entries if stamp >= today.timestamp())
                self.e.account_data['realized_pnl'] = sum(amount for stamp, amount in entries if self.session_start and stamp >= self.session_start) if self.session_start else None
        except Exception:
            self.ledger_error = 'Complete USD trading-ledger reconciliation failed; new entries are blocked'
            if self.e.account_data:
                self.e.account_data['daily_loss'] = None

    def checks(self, price):
        e, p = self.e, self.product
        account = e.account() or {}
        equity, margin, loss = (account.get(k) for k in ('equity', 'available_margin', 'daily_loss'))
        notional = e.config.quantity * float(p['contract_value']) * price * 1.02 if p and price else None
        exposure = account.get('exposure')
        unresolved = [i for i in e.storage.all('live_intent') if i['state'] in ('SUBMITTING', 'UNKNOWN', 'ACKNOWLEDGED', 'PROTECTING', 'UNPROTECTED')]
        rules = [
            ('Authentication', e.account_connected, 'Authenticated private account snapshot required'),
            ('Risk configuration', e.risk.confirmed, 'Save risk limits before starting'),
            ('Contract sizing', p is not None and 0 < e.config.quantity <= e.risk.max_quantity, f'{e.config.quantity} / {e.risk.max_quantity} integer contracts'),
            ('Market freshness', bool(e.last_update) and not e.snapshot()['market_stale'], 'Completed candles must be fresh'),
            ('Exposure', equity is not None and equity > 0 and exposure is not None and notional is not None and exposure + notional <= equity * e.risk.max_exposure_pct / 100,
             f'Requested notional with 2% price buffer: ${notional:.2f}; configured cap: {e.risk.max_exposure_pct}% of equity' if notional else 'Notional unavailable'),
            ('Available margin', margin is not None and notional is not None and notional <= margin, 'Conservative full-notional collateral check'),
            ('Daily loss', loss is not None and loss < e.risk.daily_loss_limit and not self.ledger_error, f'Gross negative USD trading-ledger debits must remain below ${e.risk.daily_loss_limit:.2f}'),
            ('Concurrent positions', not e.exchange_positions, 'One strategy position at a time; unrelated positions block new entries'),
            ('Outstanding orders', not any(o['status'] in ('OPEN', 'PENDING', 'ACKNOWLEDGED', 'SUBMITTED', 'PARTIALLY_FILLED') for o in e.orders), 'Existing active orders must be reconciled or cancelled before a new entry'),
            ('Duplicate prevention', not unresolved and not self.inflight, 'No unresolved persisted order intent'),
            ('Stop-loss policy', e.config.stop_loss_pct > 0 and e.config.take_profit_pct > 0, 'Native reduce-only stop-market exits; flatten on protection failure'),
        ]
        return [{'rule': name, 'status': 'PASSED' if ok else 'FAILED', 'detail': detail} for name, ok, detail in rules]

    def update_preflight(self):
        price = self.e.candles[-1]['close'] if self.e.candles else None
        checks = self.checks(price)
        if self.can_resume_owned_position():
            for check in checks:
                if check['rule'] in ('Exposure', 'Available margin', 'Daily loss', 'Concurrent positions', 'Outstanding orders'):
                    check.update(status='NOT EVALUATED', detail='Resuming an owned protected position; new-entry checks run again before every future entry')
        failures = [c['rule'] + ': ' + c['detail'] for c in checks if c['status'] == 'FAILED']
        self.preflight = {'ready': not failures, 'checks': checks, 'reason': '; '.join(failures) or 'Ready for protected Testnet execution'}
        return self.preflight

    def can_resume_owned_position(self):
        if not self.product or len(self.e.exchange_positions) != 1:
            return False
        position = self.e.exchange_positions[0]
        return position['symbol'] == self.product['symbol'] and any(i['purpose']=='EMA crossover entry' and i['state']=='PROTECTED'
            and i['product_id']==self.product['id'] and i['body']['side'].upper()==position['side'] for i in self.e.storage.all('live_intent'))

    def save(self, intent):
        self.e.storage.put('live_intent', intent['client_id'], intent)

    def owned_order(self, raw, intent):
        from .exchange_data import normalize
        _, _, rows = normalize({'result': []}, [], [raw], datetime.now(timezone.utc).isoformat())
        order = rows[0]
        order['correlation_id'] = intent['decision_id']
        order['reason'] = intent['purpose']
        self.e.storage.put('order', order['id'], order)
        self.e.orders = [o for o in self.e.orders if o['id'] != order['id']] + [order]
        self.e.emit('order_update', order.copy(), intent['decision_id'])
        return order

    async def submit(self, body, decision_id, purpose, suffix):
        client_id = 'al_' + hashlib.sha256((decision_id + ':' + suffix).encode()).hexdigest()[:28]
        body = {**body, 'client_order_id': client_id}
        old = self.e.storage.get('live_intent', client_id)
        if old:
            raise ValueError('Order intent already exists; reconcile instead of resubmitting')
        intent = {'client_id': client_id, 'decision_id': decision_id, 'purpose': purpose,
                  'product_id': body['product_id'], 'body': body, 'state': 'SUBMITTING', 'order_id': None}
        self.save(intent)
        self.e.emit('order_submitted', {'client_order_id': client_id, 'message': purpose}, decision_id)
        try:
            raw = await self.e.delta.create_order(body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 and exc.response.status_code not in (408, 429):
                intent['state'] = 'REJECTED'
                self.save(intent)
                raise ValueError('Delta rejected order submission; check trading permission, quantity and margin') from None
            raw = await self.recover_submission(intent)
        except Exception:
            raw = await self.recover_submission(intent)
        if not raw.get('id'):
            intent['state'] = 'UNKNOWN'
            self.save(intent)
            raise ValueError('Exchange did not return an order ID; intent requires reconciliation')
        intent.update(order_id=str(raw['id']), state='ACKNOWLEDGED')
        self.save(intent)
        self.owned_order(raw, intent)
        return raw, intent

    async def recover_submission(self, intent):
        intent['state'] = 'UNKNOWN'
        self.save(intent)
        try:
            return await self.e.delta.order_by_client(intent['client_id'])
        except Exception:
            raise ValueError('Order submission outcome is unknown. Automation stopped; no duplicate submission will be made.') from None

    async def terminal_order(self, raw, intent):
        for _ in range(12):
            if raw.get('state') in TERMINAL:
                break
            await asyncio.sleep(.5)
            raw = await self.e.delta.order_by_id(raw['id'])
        if raw.get('state') not in TERMINAL:
            await self.e.delta.cancel_order(raw['id'], intent['product_id'])
            raw = await self.e.delta.order_by_id(raw['id'])
        self.owned_order(raw, intent)
        if raw.get('state') not in TERMINAL:
            intent['state'] = 'UNKNOWN'
            self.save(intent)
            raise ValueError('Order is not terminal after cancellation; entries blocked pending reconciliation')
        return raw

    async def cancel_and_verify(self, order_id, product_id):
        raw = await self.e.delta.order_by_id(order_id)
        if raw.get('state') not in TERMINAL:
            await self.e.delta.cancel_order(order_id, product_id)
            raw = await self.e.delta.order_by_id(order_id)
        if raw.get('state') not in TERMINAL:
            raise ValueError('Order cancellation is not confirmed; new entries remain blocked')
        intent = next((i for i in self.e.storage.all('live_intent') if i.get('order_id') == str(order_id)), None)
        if intent:
            intent['state'] = 'DONE'
            self.save(intent)
            self.owned_order(raw, intent)

    async def position(self, product_id):
        raw = await self.e.delta.request('/v2/positions', {'product_id': product_id}, private=True)
        if isinstance(raw, list):
            raw = next((p for p in raw if p.get('product_id') == product_id), {})
        return raw

    async def flatten(self, product_id, correlation):
        pos = await self.position(product_id)
        size = int(pos.get('size') or 0)
        if not size:
            return
        raw, intent = await self.submit({'product_id': product_id, 'size': abs(size),
            'side': 'sell' if size > 0 else 'buy', 'order_type': 'market_order', 'reduce_only': True},
            correlation, 'Failsafe reduce-only close after protection failure', 'failsafe')
        raw = await self.terminal_order(raw, intent)
        remaining = await self.position(product_id)
        intent['state'] = 'DONE' if not int(remaining.get('size') or 0) else 'UNPROTECTED'
        self.save(intent)
        if intent['state'] != 'DONE':
            raise ValueError('Failsafe close incomplete. Position needs immediate operator inspection.')

    async def protect(self, entry, intent):
        pos = await self.position(intent['product_id'])
        size = int(pos.get('size') or 0)
        if not size:
            intent['state'] = 'UNPROTECTED'
            self.save(intent)
            raise ValueError('Filled entry is not visible in the position snapshot; reconciliation is required')
        price = Decimal(str(pos.get('entry_price') or entry.get('average_fill_price')))
        tick = Decimal(str(self.product['tick_size']))
        direction = 1 if size > 0 else -1
        def level(pct):
            value = price * (1 + Decimal(str(pct)) / 100)
            return str((value / tick).to_integral_value(rounding=ROUND_DOWN if size > 0 else ROUND_UP) * tick)
        stop, take = level(-direction * self.e.config.stop_loss_pct), level(direction * self.e.config.take_profit_pct)
        intent['state'] = 'PROTECTING'
        self.save(intent)
        exits = []
        try:
            for kind, trigger, suffix in [('stop_loss_order', stop, 'sl'), ('take_profit_order', take, 'tp')]:
                raw, exit_intent = await self.submit({'product_id': intent['product_id'], 'size': abs(size),
                    'side': 'sell' if size > 0 else 'buy', 'order_type': 'market_order', 'reduce_only': True,
                    'stop_order_type': kind, 'stop_price': trigger, 'stop_trigger_method': 'mark_price'},
                    intent['decision_id'], 'Native protective ' + kind, suffix)
                if raw.get('state') not in ('pending', 'open') or raw.get('reduce_only') is not True or raw.get('stop_order_type') != kind:
                    raise ValueError('Protective order was not accepted as active')
                exit_intent['state'] = 'PROTECTIVE'
                self.save(exit_intent)
                exits.append(raw['id'])
            intent.update(state='PROTECTED', stop_loss=float(stop), take_profit=float(take), protective_ids=exits)
            self.save(intent)
            self.e.emit('protection_active', {'message': 'Native reduce-only stop-loss and take-profit acknowledged', 'stop_loss': float(stop), 'take_profit': float(take)}, intent['decision_id'])
        except Exception:
            intent['state'] = 'UNPROTECTED'
            self.save(intent)
            # Never continue automation with an unprotected strategy position.
            await self.flatten(intent['product_id'], intent['decision_id'])
            for order_id in exits:
                await self.cancel_and_verify(order_id, intent['product_id'])
            intent['state'] = 'DONE'
            self.save(intent)
            raise ValueError('Protection setup failed. A reduce-only failsafe close was requested; inspect exchange state.') from None

    async def execute(self, decision):
        self.inflight = True
        try:
            if int((await self.position(self.product['id'])).get('size') or 0):
                raise ValueError('A position appeared during execution preparation; entry blocked')
            if await self.e.delta.orders():
                raise ValueError('Active exchange orders appeared during preparation; entry blocked')
            await self.ensure_one_x_leverage()
            raw, intent = await self.submit({'product_id': self.product['id'], 'size': self.e.config.quantity,
                'side': decision['side'].lower(), 'order_type': 'market_order', 'reduce_only': False},
                decision['id'], 'EMA crossover entry', 'entry')
            raw = await self.terminal_order(raw, intent)
            filled = int(raw.get('size', 0)) - int(raw.get('unfilled_size', raw.get('size', 0)))
            decision.update(order_id=str(raw['id']), status='FILLED' if filled == self.e.config.quantity else 'PARTIALLY_FILLED' if filled else 'CANCELLED')
            if filled:
                await self.protect(raw, intent)
            else:
                intent['state'] = 'DONE'
                self.save(intent)
        finally:
            self.inflight = False

    async def ensure_one_x_leverage(self):
        self.e.delta.require_trading_host()
        path = f"/v2/products/{self.product['id']}/orders/leverage"
        try:
            await self.e.delta.request(path, private=True, method='POST', data={'leverage': 1})
        except httpx.HTTPStatusError:
            raise ValueError('Delta refused 1x leverage setup. Verify Trading permission for this Testnet API key; no entry was submitted.') from None
        confirmation = await self.e.delta.request(path, private=True)
        if number(confirmation.get('leverage')) != 1:
            raise ValueError('Exchange did not confirm 1x leverage. Entry blocked.')

    async def close_opposite(self, decision):
        candidates = [i for i in self.e.storage.all('live_intent') if i['purpose'] == 'EMA crossover entry'
                      and i['product_id'] == self.product['id'] and i['state'] == 'PROTECTED']
        if len(candidates) != 1:
            raise ValueError('Position ownership/protection is not established; refusing to close an unrelated position')
        original = candidates[0]
        pos = await self.position(self.product['id'])
        size = int(pos.get('size') or 0)
        if not size:
            decision['status'] = 'NO TRADE'
            return
        raw, intent = await self.submit({'product_id': self.product['id'], 'size': abs(size),
            'side': 'sell' if size > 0 else 'buy', 'order_type': 'market_order', 'reduce_only': True},
            decision['id'], 'Opposite crossover reduce-only close', 'exit')
        raw = await self.terminal_order(raw, intent)
        pos = await self.position(self.product['id'])
        if int(pos.get('size') or 0):
            intent['state'] = 'UNKNOWN'
            self.save(intent)
            raise ValueError('Reduce-only close did not flatten the position; existing exits retained')
        intent['state'] = 'DONE'
        self.save(intent)
        original['state'] = 'DONE'
        self.save(original)
        for exit_id in original.get('protective_ids', []):
            await self.cancel_and_verify(exit_id, self.product['id'])
        decision.update(status='CLOSED', order_id=str(raw['id']))

    async def reconcile(self):
        for intent in self.e.storage.all('live_intent'):
            if intent['state'] in ('DONE', 'REJECTED'):
                continue
            try:
                raw = await self.e.delta.order_by_client(intent['client_id'])
            except Exception:
                if intent['state'] in ('SUBMITTING', 'UNKNOWN', 'ACKNOWLEDGED', 'PROTECTING', 'UNPROTECTED'):
                    raise ValueError('Persisted order intent could not be reconciled; no new entries are allowed') from None
                continue
            order = self.owned_order(raw, intent)
            intent['order_id'] = str(raw['id'])
            self.save(intent)
            if intent['purpose'] == 'EMA crossover entry':
                pos = await self.position(intent['product_id'])
                if not int(pos.get('size') or 0) and raw.get('state') in TERMINAL:
                    for protective_id in intent.get('protective_ids', []):
                        await self.cancel_and_verify(protective_id, intent['product_id'])
                    intent['state'] = 'DONE'
                    self.save(intent)
                elif int(pos.get('size') or 0) and intent['state'] != 'PROTECTED':
                    # On restart, do not risk adding duplicate exits after ambiguous protection.
                    await self.flatten(intent['product_id'], intent['decision_id'])
                    intent['state'] = 'DONE'
                    self.save(intent)
                elif intent['state'] == 'PROTECTED':
                    for exit_id in intent.get('protective_ids', []):
                        protective = await self.e.delta.order_by_id(exit_id)
                        if protective.get('state') not in ('open', 'pending'):
                            await self.flatten(intent['product_id'], intent['decision_id'])
                            for exit_id in intent.get('protective_ids', []):
                                await self.cancel_and_verify(exit_id, intent['product_id'])
                            intent['state'] = 'DONE'
                            self.save(intent)
                            raise ValueError('Native protection was lost. A failsafe close completed; restart automation explicitly after reviewing the position.')
            elif intent['purpose'].startswith('Native protective') and not int((await self.position(intent['product_id'])).get('size') or 0):
                await self.cancel_and_verify(raw['id'], intent['product_id'])
            elif raw.get('state') in TERMINAL:
                intent['state'] = 'DONE'
                self.save(intent)
            if intent.get('order_id') and intent['decision_id']:
                decision = self.e.storage.get('decision', intent['decision_id'])
                if decision and intent['purpose'] == 'EMA crossover entry':
                    decision.update(order_id=intent['order_id'])
                    if decision['status']=='EVALUATING':
                        decision['status']=order['status']
                    self.e.storage.put('decision', decision['id'], decision)
        self.e.decisions = self.e.storage.all('decision')

    async def cancel_entries(self):
        for intent in self.e.storage.all('live_intent'):
            if intent['purpose'] == 'EMA crossover entry' and intent['state'] not in ('DONE', 'REJECTED', 'PROTECTED'):
                raw = await self.e.delta.order_by_client(intent['client_id'])
                if raw.get('state') not in TERMINAL:
                    await self.e.delta.cancel_order(raw['id'], intent['product_id'])
        await self.reconcile()
