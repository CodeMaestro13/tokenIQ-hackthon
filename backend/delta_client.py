"""Read-only Delta adapter. Execution stays gated until account capabilities are verified.

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

    async def request(self, path, params=None, private=False):
        if not self.host:
            raise RuntimeError('Configure DELTA_TESTNET_URL for your account region')
        query = '?' + urlencode(params) if params else ''
        headers = {'User-Agent': 'AlgoLens/0.1', 'Accept': 'application/json'}
        if private:
            if not self.key or not self.secret:
                raise RuntimeError('Backend Testnet credentials are missing')
            timestamp = str(int(time.time()))
            signature = hmac.new(self.secret.encode(), ('GET' + timestamp + path + query).encode(), hashlib.sha256).hexdigest()
            headers.update({'api-key': self.key, 'timestamp': timestamp, 'signature': signature})
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(self.host + path + query, headers=headers)
            response.raise_for_status()
            body = response.json()
            if not body.get('success'):
                raise RuntimeError('Exchange request failed; check backend credentials and account region')
            return body['result']

    async def products(self):
        return await self.request('/v2/products', {'page_size': 100})

    async def balances(self):
        return await self.request('/v2/wallet/balances', private=True)

    async def positions(self):
        return await self.request('/v2/positions/margined', private=True)

    async def orders(self):
        return await self.request('/v2/orders', private=True)

    async def candles(self, symbol, timeframe):
        seconds = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600}[timeframe]
        end = int(time.time()) // seconds * seconds
        result = await self.request('/v2/history/candles', {
            'symbol': symbol, 'resolution': timeframe, 'start': end - 250 * seconds, 'end': end})
        candles = [{'time': int(c['time']), **{key: float(c[key]) for key in ('open', 'high', 'low', 'close')},
                    'volume': float(c.get('volume') or 0)} for c in result if int(c['time']) < end]
        return sorted({c['time']: c for c in candles}.values(), key=lambda c: c['time'])
