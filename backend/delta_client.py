"""Delta Testnet adapter. Production hosts are never accepted.

Reference: https://docs.delta.exchange/ (authentication and REST API).
"""
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode
import httpx


class DeltaClient:
    def __init__(self):
        self.host = os.getenv('DELTA_TESTNET_URL', '').rstrip('/')
        self.key = os.getenv('DELTA_API_KEY', '')
        self.secret = os.getenv('DELTA_API_SECRET', '')
        # Explicit allowlist: production hosts can never be configured accidentally.
        if self.host and self.host not in {
            'https://testnet-api.delta.exchange', 'https://cdn-ind.testnet.deltaex.org'
        }:
            raise ValueError('DELTA_TESTNET_URL must be a supported Testnet host')

    async def request(self, path, params=None, private=False, envelope=False, method='GET', data=None):
        if not self.host:
            raise RuntimeError('Configure DELTA_TESTNET_URL for your account region')
        query = '?' + urlencode(params) if params else ''
        body_text = json.dumps(data, separators=(',', ':')) if data is not None else ''
        headers = {'User-Agent': 'AlgoLens/0.1', 'Accept': 'application/json'}
        if private:
            if not self.key or not self.secret:
                raise RuntimeError('Backend Testnet credentials are missing')
            timestamp = str(int(time.time()))
            signature = hmac.new(self.secret.encode(), (method + timestamp + path + query + body_text).encode(), hashlib.sha256).hexdigest()
            headers.update({'api-key': self.key, 'timestamp': timestamp, 'signature': signature})
        async with httpx.AsyncClient(timeout=10) as client:
            if data is not None:
                headers['Content-Type'] = 'application/json'
            response = await client.request(method, self.host + path + query, headers=headers, content=body_text or None)
            response.raise_for_status()
            body = response.json()
            if not body.get('success'):
                raise RuntimeError('Exchange request failed; check backend credentials and account region')
            return body if envelope else body.get('result', {})

    def require_trading_host(self):
        if self.host != 'https://cdn-ind.testnet.deltaex.org':
            raise ValueError('Automated execution supports India Testnet only. Production and Global execution are disabled.')

    async def create_order(self, body):
        self.require_trading_host()
        return await self.request('/v2/orders', private=True, method='POST', data=body)

    async def cancel_order(self, order_id, product_id):
        self.require_trading_host()
        return await self.request('/v2/orders', private=True, method='DELETE', data={'id': int(order_id), 'product_id': int(product_id)})

    async def order_by_client(self, client_id):
        from urllib.parse import quote
        return await self.request('/v2/orders/client_order_id/' + quote(client_id, safe=''), private=True)

    async def order_by_id(self, order_id):
        return await self.request('/v2/orders/' + str(int(order_id)), private=True)

    async def pages(self, path, params=None, max_pages=100):
        query = {**(params or {}), 'page_size': 50}
        result, seen = [], set()
        for _ in range(max_pages):
            body = await self.request(path, query, private=True, envelope=True)
            result.extend(body['result'])
            cursor = (body.get('meta') or {}).get('after')
            if not cursor:
                return result
            if cursor in seen:
                raise ValueError('Exchange pagination did not advance; accounting is unavailable')
            seen.add(cursor)
            query['after'] = cursor
        raise ValueError('Exchange history exceeds accounting pagination limit; entries blocked')

    async def products(self):
        return await self.request('/v2/products', {'page_size': 100})

    async def balances(self):
        return await self.request('/v2/wallet/balances', private=True)

    async def positions(self):
        return await self.request('/v2/positions/margined', private=True)

    async def orders(self):
        return await self.request('/v2/orders', private=True)

    async def account_snapshot(self):
        import asyncio
        wallet, positions, orders, history = await asyncio.gather(
            self.request('/v2/wallet/balances', private=True, envelope=True),
            self.positions(), self.orders(),
            self.request('/v2/orders/history', {'page_size': 50}, private=True))
        return wallet, positions, orders + history

    async def candles(self, symbol, timeframe):
        seconds = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600}[timeframe]
        end = int(time.time()) // seconds * seconds
        result = await self.request('/v2/history/candles', {
            'symbol': symbol, 'resolution': timeframe, 'start': end - 250 * seconds, 'end': end})
        candles = [{'time': int(c['time']), **{key: float(c[key]) for key in ('open', 'high', 'low', 'close')},
                    'volume': float(c.get('volume') or 0)} for c in result if int(c['time']) < end]
        return sorted({c['time']: c for c in candles}.values(), key=lambda c: c['time'])
