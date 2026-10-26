"""FIFO closed-trade reporting for AlgoLens-owned linear USD orders.

Uses actual filled quantity, weighted fill price and paid_commission. It never
labels the BTC price change as dollar profit. Funding is outside this report.
"""
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation


def decimal(value):
    try:
        result=Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def report(orders, multipliers, owned_ids=None):
    lots=defaultdict(deque)
    trades=[]
    warnings=set()
    seen=set()
    for order in sorted(orders,key=lambda o:(o['timestamp'],o['id'])):
        if order['id'] in seen or (owned_ids is not None and order['id'] not in owned_ids):
            continue
        seen.add(order['id'])
        quantity=decimal(order.get('filled_quantity'))
        price=decimal(order.get('average_fill_price'))
        if quantity is None or quantity<=0 or price is None or price<=0:
            continue
        symbol=order['symbol']
        multiplier=decimal(multipliers.get(symbol))
        if multiplier is None or multiplier<=0:
            warnings.add(f'{symbol}: contract multiplier is unavailable; results omitted')
            continue
        fee=decimal(order.get('paid_commission'))
        unit_fee=fee/quantity if fee is not None else None
        remaining=quantity
        side=order['side']
        if side not in ('BUY','SELL'):
            continue
        while remaining>0 and lots[symbol] and lots[symbol][0]['side']!=side:
            entry=lots[symbol][0]
            matched=min(remaining,entry['remaining'])
            gross=(price-entry['price'])*matched*multiplier*(1 if entry['side']=='BUY' else -1)
            entry_fee=entry['unit_fee']*matched if entry['unit_fee'] is not None else None
            exit_fee=unit_fee*matched if unit_fee is not None else None
            fees=entry_fee+exit_fee if entry_fee is not None and exit_fee is not None else None
            trades.append({'id':f"{entry['order']['id']}:{order['id']}:{len(trades)}",'symbol':symbol,
                'side':'LONG' if entry['side']=='BUY' else 'SHORT','quantity':float(matched),
                'contract_value':float(multiplier),'base_quantity':float(matched*multiplier),
                'entry_price':float(entry['price']),'exit_price':float(price),
                'gross_pnl':float(gross),'entry_fee':float(entry_fee) if entry_fee is not None else None,
                'exit_fee':float(exit_fee) if exit_fee is not None else None,
                'fees':float(fees) if fees is not None else None,'net_pnl':float(gross-fees) if fees is not None else None,
                'opened_at':entry['order']['timestamp'],'closed_at':order.get('updated_at') or order['timestamp'],
                'entry_order_id':entry['order']['id'],'exit_order_id':order['id'],'currency':'USD',
                'mode':order['mode']})
            remaining-=matched
            entry['remaining']-=matched
            if not entry['remaining']:
                lots[symbol].popleft()
        if remaining>0:
            if order.get('reduce_only'):
                warnings.add(f'{symbol}: exit quantity has no matching loaded entry; unmatched portion omitted')
            else:
                lots[symbol].append({'side':side,'remaining':remaining,'price':price,'unit_fee':unit_fee,'order':order})
    known_fees=all(t['fees'] is not None for t in trades)
    if not known_fees:
        warnings.add('Some paid commission values are missing; net P&L is unavailable for those trades')
    return {'trades':list(reversed(trades)), 'closed_count':len(trades),
            'gross_pnl':float(sum((decimal(t['gross_pnl']) for t in trades),Decimal(0))),
            'fees':float(sum((decimal(t['fees']) for t in trades),Decimal(0))) if known_fees else None,
            'net_pnl':float(sum((decimal(t['net_pnl']) for t in trades),Decimal(0))) if known_fees else None,
            'warnings':sorted(warnings),'scope':'AlgoLens matched closed trades in loaded order history; includes trading fees, excludes funding and transfers'}
