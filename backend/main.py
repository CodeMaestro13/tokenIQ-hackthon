import asyncio
import os
import uuid
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .engine import Engine, now
from .schemas import StrategyConfig, RiskConfig, Event

engine = None


@asynccontextmanager
async def lifespan(app):
    global engine
    engine = Engine()
    task = asyncio.create_task(engine.run())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    engine.storage.db.close()


app = FastAPI(title='AlgoLens', version='0.1.0', lifespan=lifespan)
origins = os.getenv('FRONTEND_ORIGIN', 'http://localhost:3000').split(',')
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET', 'POST', 'PUT'], allow_headers=['Content-Type'])


@app.middleware('http')
async def local_controls(request: Request, call_next):
    if request.method in ('POST', 'PUT', 'DELETE'):
        if request.client.host not in ('127.0.0.1', '::1', 'testclient'):
            return JSONResponse(status_code=403, content={'code': 'LOCAL_ONLY', 'message': 'Trading controls require a local connection', 'correlation_id': uuid.uuid4().hex})
        origin = request.headers.get('origin')
        if origin and origin not in origins:
            return JSONResponse(status_code=403, content={'code': 'ORIGIN_REJECTED', 'message': 'Origin not allowed', 'correlation_id': uuid.uuid4().hex})
    return await call_next(request)


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse(status_code=409, content={'code': 'ACTION_REJECTED', 'message': str(exc), 'correlation_id': uuid.uuid4().hex})


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(status_code=422, content={'code': 'VALIDATION_ERROR', 'message': '; '.join(e['msg'] for e in exc.errors()), 'correlation_id': uuid.uuid4().hex})


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(status_code=exc.status_code, content={'code': 'REQUEST_FAILED', 'message': str(exc.detail), 'correlation_id': uuid.uuid4().hex})


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    return JSONResponse(status_code=500, content={'code': 'INTERNAL_ERROR', 'message': 'Unexpected backend error. Trading state should be checked before retrying.', 'correlation_id': uuid.uuid4().hex})


@app.get('/api/health')
def health():
    return {'status': 'ok', 'mode': engine.mode, 'as_of': now()}


@app.get('/api/ready')
def ready():
    state=engine.snapshot()
    return {'ready': engine.mode == 'demo' or engine.exchange_connected,
            'execution_enabled': state['execution_enabled'],
            'trading_ready': engine.mode == 'demo' or bool(engine.trader.preflight['ready'])}


@app.get('/api/snapshot')
def snapshot():
    return engine.snapshot()


@app.get('/api/account')
@app.get('/api/account/balance')
def account():
    return {'mode': engine.mode, 'as_of': engine.last_update, 'data': engine.account()}


@app.get('/api/markets')
async def markets():
    if engine.mode == 'demo':
        return [{'symbol': 'BTCUSD', 'contract_value': '0.001', 'quantity_step': 1, 'mode': 'demo'}]
    try:
        products = await engine.delta.products()
        return [{'symbol': p['symbol'], 'contract_value': p['contract_value'], 'tick_size': p['tick_size'], 'mode': 'testnet'}
                for p in products if p.get('state')=='live' and p.get('contract_type')=='perpetual_futures'
                and p.get('notional_type')=='vanilla' and (p.get('settling_asset') or {}).get('symbol')=='USD'
                and (p.get('quoting_asset') or {}).get('symbol')=='USD']
    except Exception:
        raise HTTPException(503, 'Unable to retrieve Testnet instruments')


@app.get('/api/market/candles')
def candles():
    return {'mode': engine.mode, 'as_of': engine.last_update, 'data': engine.candles}


@app.get('/api/market/ticker')
def ticker():
    return {'mode': engine.mode, 'as_of': engine.last_update, 'price': engine.candles[-1]['close'] if engine.candles else None}


@app.get('/api/strategy/status')
def status():
    return {'status': engine.status, 'mode': engine.mode}


@app.get('/api/strategy/config', response_model=StrategyConfig)
def config():
    return engine.config


@app.put('/api/strategy/config', response_model=StrategyConfig)
async def save_config(config: StrategyConfig):
    async with engine.lock:
        if engine.status == 'RUNNING' or engine.position or engine.exchange_positions:
            raise ValueError('Stop the strategy and wait for positions to close before changing configuration')
        if engine.mode == 'demo' and config.symbol != 'BTCUSD':
            raise ValueError('Demo supports BTCUSD only')
        changed = config.timeframe != engine.config.timeframe or config.symbol != engine.config.symbol
        if engine.mode=='testnet':
            product=await engine.delta.request('/v2/products/'+config.symbol)
            if not (product.get('state')=='live' and product.get('contract_type')=='perpetual_futures' and product.get('notional_type')=='vanilla'
                    and (product.get('settling_asset') or {}).get('symbol')=='USD' and (product.get('quoting_asset') or {}).get('symbol')=='USD'):
                raise ValueError('Select a supported USD-settled linear perpetual instrument')
        engine.config = config
        if changed and engine.mode == 'demo':
            seconds = {'1m': 60, '5m': 300, '15m': 900}[config.timeframe]
            base = int(__import__('time').time()) // seconds * seconds - 120 * seconds
            engine.candles = [engine.demo_candle(base + i * seconds, i) for i in range(120)]
            engine.step = 120
            engine.storage.put('state', 'market', {'candles': engine.candles, 'step': engine.step})
        if changed and engine.mode=='testnet':
            engine.candles=[]
            engine.last_update=None
            engine.latest_evaluation=None
            engine.last_observed_candle=None
            engine.trader.product=None
            engine.trader.preflight={'ready':False,'checks':[],'reason':'Refreshing the selected instrument'}
        engine.storage.put('config', 'strategy', config.model_dump())
        engine.emit('config_update', {'message': 'Strategy configuration saved'})
        return config


@app.post('/api/strategy/start')
async def start():
    await engine.start()
    return status()


@app.post('/api/strategy/stop')
async def stop():
    await engine.stop()
    return status()


@app.post('/api/strategy/emergency-stop')
async def emergency():
    await engine.stop(True)
    return status()


@app.get('/api/positions')
def positions():
    return engine.positions()


@app.get('/api/orders')
def orders(status: str | None = None, side: str | None = None, symbol: str | None = None,
           start: str | None = None, end: str | None = None,
           page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    data = [o for o in reversed(engine.orders) if (not status or o['status'] == status or
            (status == 'OPEN' and o['status'] in ('OPEN', 'PENDING', 'SUBMITTED', 'ACKNOWLEDGED', 'PARTIALLY_FILLED'))) and
            (not side or o['side'] == side) and (not symbol or o['symbol'] == symbol) and
            (not start or o['timestamp'] >= start) and (not end or o['timestamp'] <= end)]
    return {'items': data[(page-1)*page_size:page*page_size], 'total': len(data), 'page': page}


@app.get('/api/orders/{order_id}')
def order(order_id: str):
    result = next((o for o in engine.orders if o['id'] == order_id), None)
    if result is None:
        raise HTTPException(404, 'Order not found')
    return result


@app.get('/api/risk/config', response_model=RiskConfig)
def risk_config():
    return engine.risk


@app.put('/api/risk/config', response_model=RiskConfig)
async def save_risk(config: RiskConfig):
    async with engine.lock:
        if engine.status == 'RUNNING':
            raise ValueError('Stop the strategy before changing risk limits')
        engine.risk = config
        engine.storage.put('config', 'risk', config.model_dump())
        engine.emit('risk_config', {'message': 'Risk limits saved', **config.model_dump()})
        if engine.trader:
            engine.trader.update_preflight()
        return config


@app.get('/api/risk/status')
def risk_status():
    return {'config': engine.risk.model_dump(), 'account': engine.account()}


@app.get('/api/risk/rejections')
def rejections():
    return [d for d in engine.decisions if d['status'] == 'REJECTED']


@app.get('/api/events', response_model=list[Event])
def events(after: int = 0, severity: str | None = None, type: str | None = None):
    return [e for e in engine.events if e['sequence'] > after and (not severity or e['severity'] == severity) and (not type or e['type'] == type)]


@app.get('/api/decisions/{decision_id}')
def decision(decision_id: str):
    result = engine.storage.get('decision', decision_id)
    if result is None:
        raise HTTPException(404, 'Decision not found')
    return result


@app.post('/api/connection/test')
async def connection():
    if engine.mode == 'demo':
        return {'mode': 'demo', 'connected': False, 'message': 'Demo Mode uses simulated data; no exchange connection is claimed.'}
    try:
        products = await engine.delta.products()
        await engine.refresh_account()
        if not engine.account_connected:
            raise HTTPException(503, engine.account_error)
        return {'mode': 'testnet', 'connected': True, 'message': f'Public instruments and private account access verified ({len(products)} instruments). Check Strategy Control preflight before starting.'}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Testnet connection failed. Check host, API permissions and IP allowlist.')


@app.websocket('/ws/trading')
async def socket(ws: WebSocket):
    if ws.headers.get('origin') and ws.headers['origin'] not in origins:
        await ws.close(code=1008)
        return
    await ws.accept()
    queue = asyncio.Queue(maxsize=200)
    engine.clients.add(queue)
    try:
        await ws.send_json({'type': 'snapshot_required', 'sequence': engine.sequence})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
                await ws.send_json(event)
            except asyncio.TimeoutError:
                await ws.send_json({'type': 'heartbeat', 'sequence': engine.sequence})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        engine.clients.discard(queue)
