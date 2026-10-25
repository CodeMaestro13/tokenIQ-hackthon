import asyncio
import copy
import time
import httpx
import pytest
from backend.engine import Engine
from backend.schemas import RiskConfig, StrategyConfig


class Exchange:
    host='https://cdn-ind.testnet.deltaex.org'
    def __init__(self):
        self.created=[]
        self.rows={}
        self.size=0
        self.fail_tp=False
        self.timeout_entry=False
        self.unknown_entry=False
        self.ledger=[]
        self.partial=False

    def require_trading_host(self):
        if self.host!='https://cdn-ind.testnet.deltaex.org':
            raise ValueError('India Testnet only')

    async def request(self,path,params=None,**kwargs):
        if path.endswith('/orders/leverage'):
            return {'leverage':1}
        if path.startswith('/v2/products/'):
            return {'id':84,'symbol':'BTCUSD','state':'live','contract_type':'perpetual_futures','notional_type':'vanilla','contract_value':'0.001','tick_size':'0.1','settling_asset':{'id':3,'symbol':'USD'},'quoting_asset':{'symbol':'USD'}}
        if path=='/v2/positions':
            return {'size':self.size,'entry_price':'80000','product_id':84}
        if path.startswith('/v2/tickers/'):
            return {'mark_price':'80000'}
        raise AssertionError(path)

    async def pages(self,path,params):
        return self.ledger

    async def account_snapshot(self):
        wallet={'result':[{'asset_symbol':'USD','balance':'10000','available_balance':'10000'}],'meta':{'net_equity':'10000'}}
        positions=[{'product_id':84,'product_symbol':'BTCUSD','size':self.size,'entry_price':'80000','mark_price':'80000','unrealized_pnl':'0'}] if self.size else []
        return wallet,positions,list(self.rows.values())

    async def create_order(self,body):
        self.created.append(copy.deepcopy(body))
        if self.fail_tp and body.get('stop_order_type')=='take_profit_order':
            request=httpx.Request('POST','https://example.invalid')
            raise httpx.HTTPStatusError('rejected',request=request,response=httpx.Response(400,request=request))
        if self.unknown_entry and not body.get('reduce_only'):
            raise httpx.ReadTimeout('submission uncertain')
        oid=len(self.rows)+1
        stop=bool(body.get('stop_order_type'))
        row={**body,'id':oid,'product_symbol':'BTCUSD','state':'pending' if stop else 'closed',
             'unfilled_size':body['size'] if stop else 0,'average_fill_price':None if stop else '80000',
             'created_at':int(time.time()*1e6)}
        self.rows[str(oid)]=row
        if not stop:
            self.size=0 if body.get('reduce_only') else body['size']*(1 if body['side']=='buy' else -1)
            if self.partial and not body.get('reduce_only'):
                row.update(state='cancelled',unfilled_size=1)
                self.size=(body['size']-1)*(1 if body['side']=='buy' else -1)
        if self.timeout_entry and not body.get('reduce_only'):
            raise httpx.ReadTimeout('server accepted but response timed out')
        return copy.deepcopy(row)

    async def order_by_client(self,client):
        for row in self.rows.values():
            if row['client_order_id']==client:return copy.deepcopy(row)
        request=httpx.Request('GET','https://example.invalid')
        raise httpx.HTTPStatusError('not found',request=request,response=httpx.Response(404,request=request))

    async def order_by_id(self,oid):
        return copy.deepcopy(self.rows[str(oid)])

    async def orders(self):
        return [copy.deepcopy(o) for o in self.rows.values() if o['state'] not in ('closed','cancelled','rejected')]

    async def cancel_order(self,oid,pid):
        self.rows[str(oid)]['state']='cancelled'
        return {}


def setup(tmp_path):
    engine=Engine(str(tmp_path/'live.db'),'testnet')
    engine.delta=Exchange()
    engine.risk=RiskConfig(confirmed=True)
    engine.config=StrategyConfig(fast_period=2,slow_period=3)
    end=int(time.time())//60*60-60
    engine.candles=[{'time':end-(4-i)*60,'open':v,'high':v,'low':v,'close':v,'volume':1} for i,v in enumerate([80004,80003,80002,80001,80006])]
    engine.last_update=__import__('backend.engine',fromlist=['now']).now()
    return engine


async def trade(engine):
    await engine.start()
    engine.trader.last_candle=engine.candles[-2]['time']
    await engine.execute_testnet_signal()


def test_real_execution_path_builds_native_protection_and_preserves_it_on_stop(tmp_path):
    engine=setup(tmp_path)
    asyncio.run(trade(engine))
    assert engine.status=='RUNNING'
    assert len(engine.delta.created)==3
    assert not engine.delta.created[0]['reduce_only']
    assert all(o['reduce_only'] and o['order_type']=='market_order' for o in engine.delta.created[1:])
    assert {o['stop_price'] for o in engine.delta.created[1:]}=={'79200.0','81600.0'}
    assert engine.decisions[-1]['status']=='FILLED'
    assert next(i for i in engine.storage.all('live_intent') if i['purpose']=='EMA crossover entry')['state']=='PROTECTED'
    asyncio.run(engine.stop(True))
    assert engine.delta.size==1
    assert all(o['state']=='pending' for o in list(engine.delta.rows.values())[1:])
    count=len(engine.delta.created)
    asyncio.run(engine.execute_testnet_signal())
    assert len(engine.delta.created)==count


def test_submission_timeout_recovers_without_duplicate_entry(tmp_path):
    engine=setup(tmp_path)
    engine.delta.timeout_entry=True
    asyncio.run(trade(engine))
    assert engine.status=='RUNNING'
    assert len([o for o in engine.delta.created if not o.get('reduce_only')])==1
    assert next(i for i in engine.storage.all('live_intent') if i['purpose']=='EMA crossover entry')['state']=='PROTECTED'


def test_unknown_submission_stops_and_does_not_retry(tmp_path):
    engine=setup(tmp_path)
    engine.delta.unknown_entry=True
    asyncio.run(trade(engine))
    assert engine.status=='ERROR'
    assert len(engine.delta.created)==1
    assert engine.storage.all('live_intent')[0]['state']=='UNKNOWN'
    with pytest.raises(ValueError,match='reconciled'):
        asyncio.run(engine.start())
    assert len(engine.delta.created)==1


def test_protection_rejection_flattens_and_stops(tmp_path):
    engine=setup(tmp_path)
    engine.delta.fail_tp=True
    asyncio.run(trade(engine))
    assert engine.status=='ERROR'
    assert engine.delta.size==0
    assert engine.delta.created[-1]['reduce_only']
    assert all(r['state']!='pending' for r in engine.delta.rows.values())


def test_start_explains_exposure_without_relaxing_limits(tmp_path):
    engine=setup(tmp_path)
    async def low_balance():
        return {'result':[{'asset_symbol':'USD','balance':'100','available_balance':'100'}]},[],[]
    engine.delta.account_snapshot=low_balance
    with pytest.raises(ValueError,match='Exposure'):
        asyncio.run(engine.start())
    assert engine.risk.max_exposure_pct==20
    assert engine.delta.created==[]


def test_negative_ledger_debits_include_fees_and_ignore_deposits(tmp_path):
    engine=setup(tmp_path)
    stamp=__import__('backend.engine',fromlist=['now']).now()
    engine.delta.ledger=[{'transaction_type':kind,'amount':amount,'created_at':stamp} for kind,amount in [('cashflow','-3'),('cashflow','5'),('commission','-.5'),('funding','-.2'),('deposit','100')]]
    asyncio.run(engine.refresh_account())
    asyncio.run(engine.trader.prepare())
    assert engine.account()['daily_loss']==pytest.approx(3.7)


def test_global_and_production_execution_are_refused(tmp_path):
    engine=setup(tmp_path)
    engine.delta.host='https://testnet-api.delta.exchange'
    with pytest.raises(ValueError,match='India Testnet'):
        asyncio.run(engine.start())
    assert not engine.delta.created


def test_opposite_crossover_closes_owned_position_without_reversing(tmp_path):
    engine=setup(tmp_path)
    asyncio.run(trade(engine))
    asyncio.run(engine.refresh_account())
    engine.candles=[{**c,'close':v} for c,v in zip(engine.candles,[80001,80002,80003,80004,80000])]
    engine.candles[-1]['time']+=60
    asyncio.run(engine.execute_testnet_signal())
    assert engine.delta.size==0
    assert engine.delta.created[-1]['reduce_only']
    assert len([o for o in engine.delta.created if not o['reduce_only']])==1
    assert engine.decisions[-1]['status']=='CLOSED'
    assert all(r['state']!='pending' for r in engine.delta.rows.values())


def test_resume_preserves_protected_position(tmp_path):
    engine=setup(tmp_path)
    asyncio.run(trade(engine))
    asyncio.run(engine.stop())
    asyncio.run(engine.start())
    assert engine.status=='RUNNING'
    assert engine.delta.size==1
    assert len(engine.delta.created)==3


def test_failed_accounting_blocks_start(tmp_path):
    engine=setup(tmp_path)
    async def failed(*args,**kwargs):
        raise ValueError('Pagination incomplete')
    engine.delta.pages=failed
    with pytest.raises(ValueError,match='Daily loss'):
        asyncio.run(engine.start())
    assert not engine.delta.created


def test_partial_fill_protects_only_actual_filled_contracts(tmp_path):
    engine=setup(tmp_path)
    engine.config=StrategyConfig(fast_period=2,slow_period=3,quantity=2)
    engine.delta.partial=True
    asyncio.run(trade(engine))
    assert engine.delta.size==1
    assert engine.decisions[-1]['status']=='PARTIALLY_FILLED'
    assert all(o['size']==1 for o in engine.delta.created if o.get('stop_order_type'))


def test_repeated_candle_cannot_submit_second_entry(tmp_path):
    engine=setup(tmp_path)
    asyncio.run(trade(engine))
    engine.trader.last_candle=engine.candles[-2]['time']
    before=len(engine.delta.created)
    asyncio.run(engine.execute_testnet_signal())
    assert len(engine.delta.created)==before


def test_lost_native_stop_flattens_and_requires_restart(tmp_path):
    engine=setup(tmp_path)
    asyncio.run(trade(engine))
    sl=next(r for r in engine.delta.rows.values() if r.get('stop_order_type')=='stop_loss_order')
    sl['state']='cancelled'
    with pytest.raises(ValueError,match='protection was lost'):
        asyncio.run(engine.trader.reconcile())
    assert engine.delta.size==0
    assert all(r['state']!='pending' for r in engine.delta.rows.values())
