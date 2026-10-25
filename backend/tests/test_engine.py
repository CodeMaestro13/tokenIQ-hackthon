import asyncio
import pytest
from pydantic import ValidationError
from backend.engine import Engine
from backend.schemas import StrategyConfig, RiskConfig
from backend.strategy import ema, evaluate
from backend.risk_manager import validate


def run(coro):
    return asyncio.run(coro)


def test_ema_seed_and_warmup():
    assert ema([1,2],3) == [None,None]
    assert ema([1,2,3,4],3) == [None,None,2,3]
    assert evaluate([{'close':1,'time':1}],StrategyConfig()) is None


def test_crossover_and_no_signal():
    c=StrategyConfig(fast_period=2,slow_period=3)
    candles=[{'close':v,'time':i} for i,v in enumerate([4,3,2,1,6])]
    assert evaluate(candles,c)['side']=='BUY'
    assert evaluate([{'close':v,'time':i} for i,v in enumerate([1,2,3,4,0])],c)['side']=='SELL'
    assert evaluate([{'close':1,'time':i} for i in range(5)],c)['side']=='HOLD'


def test_configuration_rejected():
    with pytest.raises(ValidationError):
        StrategyConfig(fast_period=50,slow_period=20)
    with pytest.raises(ValidationError):
        StrategyConfig(quantity=0)
    with pytest.raises(ValidationError):
        RiskConfig(max_exposure_pct=101)


def test_risk_checks_fail_independently():
    c=StrategyConfig(quantity=10)
    limits=RiskConfig(max_quantity=1,max_exposure_pct=.01,daily_loss_limit=1)
    checks=validate(c,limits,{'equity':100,'available_margin':0,'daily_loss':2},67000,None,True)
    failed={v['rule'] for v in checks if v['status']=='FAILED'}
    assert {'Position size','Exposure','Available margin','Daily loss','Duplicate prevention','Risk configuration'}<=failed


def test_full_demo_lifecycle_and_restart(tmp_path):
    path=str(tmp_path/'demo.db')
    engine=Engine(path,mode='demo')
    with pytest.raises(ValueError):
        run(engine.start())
    engine.risk=RiskConfig(confirmed=True)
    engine.storage.put('config','risk',engine.risk.model_dump())
    run(engine.start())
    run(engine.start())
    for _ in range(160):
        run(engine.tick())
    assert len(engine.decisions)>1
    assert any(d['status']=='FILLED' for d in engine.decisions)
    assert engine.orders
    assert all(o['mode']=='demo' for o in engine.orders)
    assert all(d['risk_checks'] for d in engine.decisions if d['status']=='FILLED')
    assert engine.storage.claim('dedup',{})
    assert not engine.storage.claim('dedup',{})
    assert len({e['sequence'] for e in engine.events})==len(engine.events)
    count=len(engine.orders)
    run(engine.stop())
    run(engine.tick())
    assert engine.status=='STOPPED'
    restarted=Engine(path,mode='demo')
    assert restarted.status=='STOPPED'
    assert restarted.risk.confirmed
    assert len(restarted.orders)>=count
    assert restarted.decisions
    restarted.storage.db.close()
    engine.storage.db.close()


def test_stop_preserves_open_position(tmp_path):
    engine=Engine(str(tmp_path/'stop.db'),'demo')
    engine.risk=RiskConfig(confirmed=True)
    run(engine.start())
    for _ in range(100):
        run(engine.tick())
        if engine.position:
            break
    assert engine.position
    previous=engine.position.copy()
    run(engine.stop(True))
    assert engine.position==previous
    assert engine.status=='STOPPED'
    engine.storage.db.close()


def test_testnet_never_falls_back(tmp_path):
    engine=Engine(str(tmp_path/'testnet.db'),'testnet')
    assert engine.account() is None
    assert engine.candles==[]
    assert engine.orders==[]
    assert not engine.snapshot()['execution_enabled']
    with pytest.raises(ValueError,match='execution locked'):
        run(engine.start())
    engine.storage.db.close()


def test_modes_cannot_share_database(tmp_path):
    path=str(tmp_path/'isolated.db')
    demo=Engine(path,'demo')
    demo.storage.db.close()
    with pytest.raises(ValueError,match='another mode'):
        Engine(path,'testnet')


def test_market_clock_is_restored(tmp_path):
    path=str(tmp_path/'clock.db')
    engine=Engine(path,'demo')
    run(engine.tick())
    last=engine.candles[-1]
    engine.storage.db.close()
    restarted=Engine(path,'demo')
    assert restarted.candles[-1]==last
    run(restarted.tick())
    assert restarted.candles[-1]['time']==last['time']+60
    restarted.storage.db.close()
