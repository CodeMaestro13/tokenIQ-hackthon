import asyncio
import httpx
from backend.engine import Engine
from backend.exchange_data import normalize, connection_error
from backend.schemas import StrategyConfig


def test_private_snapshot_preserves_real_values_and_unknown_metrics():
    wallet={'result':[{'asset_symbol':'USD','balance':'500','available_balance':'450'}], 'meta':{'net_equity':'510'}}
    p=[{'product_id':27,'product_symbol':'BTCUSD','size':-2,'entry_price':'70000','mark_price':'69000','unrealized_pnl':'2'}]
    raw=[{'id':123,'product_symbol':'BTCUSD','size':2,'unfilled_size':1,'side':'buy','state':'open','created_at':'1725865012000000'}]
    account, positions, orders=normalize(wallet,p,raw+raw,'2026-10-25T00:00:00+00:00')
    assert account['equity']==510 and account['available_margin']==450
    assert account['realized_pnl'] is None and account['daily_loss'] is None
    assert positions[0]['side']=='SELL' and positions[0]['unrealized_pnl']==2
    assert positions[0]['stop_loss'] is None
    assert len(orders)==1 and orders[0]['status']=='PARTIALLY_FILLED'
    assert orders[0]['filled_quantity']==1
    assert orders[0]['timestamp'].startswith('2024-09-09')


def test_flat_account_has_verified_zero_unrealized_pnl():
    account,positions,orders=normalize({'result':[{'asset_symbol':'USD','balance':'500','available_balance':'500'}]},[],[],'now')
    assert account['equity']==500 and account['unrealized_pnl']==0 and account['exposure']==0
    assert account['daily_loss'] is None


def test_no_usd_wallet_never_invents_conversion():
    account,_,_=normalize({'result':[{'asset_symbol':'BTC','balance':'1'}]},[],[],'now')
    assert account is None


def test_ip_whitelist_error_does_not_leak_headers():
    request=httpx.Request('GET','https://example.invalid',headers={'api-key':'must-not-appear'})
    response=httpx.Response(401,request=request,json={'error':{'code':'ip_not_whitelisted_for_api_key'}})
    message=connection_error(httpx.HTTPStatusError('error',request=request,response=response))
    assert 'public IP' in message and 'must-not-appear' not in message


def test_read_only_monitor_evaluates_without_any_orders(tmp_path):
    engine=Engine(str(tmp_path/'monitor.db'),'testnet')
    engine.config=StrategyConfig(fast_period=2,slow_period=3)
    engine.candles=[{'time':i,'close':v} for i,v in enumerate([4,3,2,1,6])]
    engine.observe_strategy()
    engine.observe_strategy()
    assert engine.latest_evaluation['side']=='BUY'
    assert len(engine.decisions)==1 and engine.decisions[0]['status']=='OBSERVED'
    assert all(c['status']=='NOT EVALUATED' for c in engine.decisions[0]['risk_checks'])
    assert engine.orders==[] and engine.status=='STOPPED'
    assert engine.snapshot()['strategy_monitoring']
    engine.storage.db.close()


def test_account_refresh_failure_keeps_public_feed_independent(tmp_path):
    engine=Engine(str(tmp_path/'auth.db'),'testnet')
    engine.exchange_connected=True
    async def failed():
        raise RuntimeError('secret text must not leak')
    engine.delta.account_snapshot=failed
    asyncio.run(engine.refresh_account())
    assert engine.exchange_connected and not engine.account_connected
    assert engine.account() is None and 'secret text' not in engine.account_error
    engine.storage.db.close()
