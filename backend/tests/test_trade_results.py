import pytest
from backend.trade_results import report


def order(oid,side,price,qty,fee,reduce=False,when='2026-10-25T11:00:00Z'):
    return {'id':str(oid),'symbol':'BTCUSD','side':side,'average_fill_price':price,
            'filled_quantity':qty,'paid_commission':fee,'reduce_only':reduce,'timestamp':when,'mode':'testnet'}


def test_verified_trade_gross_and_net_are_separate():
    orders=[order(1,'BUY',80377.5,1,.04268046),order(2,'SELL',80417.5,1,.0427017,True,'2026-10-25T12:22:00Z')]
    result=report(orders,{'BTCUSD':'.001'})
    assert result['closed_count']==1
    assert result['gross_pnl']==pytest.approx(.04)
    assert result['fees']==pytest.approx(.08538216)
    assert result['net_pnl']==pytest.approx(-.04538216)
    assert result['trades'][0]['base_quantity']==.001


def test_short_trade_and_partial_exit_fee_allocation():
    orders=[order(1,'SELL',80000,2,.08),order(2,'BUY',79900,1,.04,True,'2026-10-25T12:00:00Z')]
    result=report(orders,{'BTCUSD':'.001'})
    assert result['gross_pnl']==.1
    assert result['fees']==.08
    assert result['net_pnl']==.02
    assert result['trades'][0]['quantity']==1


def test_open_orders_do_not_create_realized_profit():
    result=report([order(1,'BUY',80000,1,.04)],{'BTCUSD':'.001'})
    assert result['closed_count']==0


def test_missing_fees_never_become_zero():
    result=report([order(1,'BUY',80000,1,None),order(2,'SELL',80100,1,.04,True,'2026-10-25T12:00:00Z')],{'BTCUSD':'.001'})
    assert result['gross_pnl']==.1
    assert result['fees'] is None and result['net_pnl'] is None


def test_unfilled_protection_and_duplicate_orders_are_not_trades():
    entry=order(1,'BUY',80000,1,.04)
    result=report([entry,entry,order(2,'SELL',None,0,0,True)],{'BTCUSD':'.001'})
    assert result['closed_count']==0


def test_unowned_orders_and_unknown_multiplier_are_not_fabricated():
    orders=[order(1,'BUY',80000,1,.04),order(2,'SELL',80100,1,.04,True,'2026-10-25T12:00:00Z')]
    assert report(orders,{'BTCUSD':'.001'},{'1'})['closed_count']==0
    result=report(orders,{})
    assert result['closed_count']==0 and result['warnings']
