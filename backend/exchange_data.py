"""Normalize read-only exchange data without inventing missing financial values."""
from datetime import datetime, timezone
import math


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def timestamp(value):
    if isinstance(value, str) and 'T' in value:
        return value
    numeric = number(value)
    if numeric is None:
        return None
    # Delta order timestamps are typically microseconds since the epoch.
    if numeric > 1e14:
        numeric /= 1e6
    elif numeric > 1e11:
        numeric /= 1e3
    return datetime.fromtimestamp(numeric, timezone.utc).isoformat()


def normalize(wallet, positions, orders, updated_at):
    normalized_positions = []
    for p in positions:
        size = number(p.get('size'))
        if not size:
            continue
        normalized_positions.append({
            'id': str(p['product_id']), 'symbol': p.get('product_symbol', str(p['product_id'])),
            'side': 'BUY' if size > 0 else 'SELL', 'quantity': abs(size),
            'entry_price': number(p.get('entry_price')), 'mark_price': number(p.get('mark_price')),
            'unrealized_pnl': number(p.get('unrealized_pnl')),
            'stop_loss': None, 'take_profit': None, 'updated_at': p.get('updated_at') or updated_at,
            'strategy': 'EXCHANGE_POSITION', 'protection': 'NOT VERIFIED',
        })
    normalized_orders = {}
    for o in orders:
        key = str(o['id'])
        if key in normalized_orders:
            continue
        quantity, unfilled = number(o.get('size')), number(o.get('unfilled_size'))
        filled = max(0, quantity - unfilled) if quantity is not None and unfilled is not None else None
        state = o.get('state', 'unknown')
        status = {'open': 'OPEN', 'pending': 'PENDING', 'cancelled': 'CANCELLED', 'rejected': 'REJECTED'}.get(state, 'UNKNOWN')
        if state == 'closed':
            status = 'FILLED' if quantity and filled == quantity else 'CLOSED'
        elif state == 'open' and filled:
            status = 'PARTIALLY_FILLED'
        normalized_orders[key] = {
            'id': key, 'symbol': o.get('product_symbol', str(o.get('product_id', ''))),
            'side': str(o.get('side', '')).upper(), 'quantity': quantity, 'filled_quantity': filled,
            'average_fill_price': number(o.get('average_fill_price')), 'type': o.get('order_type', 'UNKNOWN'),
            'status': status, 'timestamp': timestamp(o.get('created_at')) or updated_at,
            'correlation_id': 'exchange:' + key, 'reduce_only': bool(o.get('reduce_only')),
            'reason': 'Imported exchange order; not submitted by AlgoLens', 'mode': 'testnet',
        }
    # Present only explicit USD wallet values. Do not combine currencies or invent session P&L.
    usd = next((w for w in wallet.get('result', []) if w.get('asset_symbol') == 'USD'), None)
    account = None
    if usd:
        account = {'equity': number(wallet.get('meta', {}).get('net_equity')),
                   'wallet_balance': number(usd.get('balance')),
                   'available_margin': number(usd.get('available_balance')),
                   'unrealized_pnl': None, 'realized_pnl': None, 'daily_loss': None,
                   'exposure': None, 'currency': 'USD', 'active_positions': len(normalized_positions)}
        if not normalized_positions:
            account['unrealized_pnl'] = 0
            account['exposure'] = 0
            if account['equity'] is None:
                account['equity'] = account['wallet_balance']
    return account, normalized_positions, sorted(normalized_orders.values(), key=lambda o: o['timestamp'])


def connection_error(exc):
    response = getattr(exc, 'response', None)
    if response is not None:
        try:
            error = response.json().get('error', {})
            code = error.get('code') if isinstance(error, dict) else error
            if code == 'ip_not_whitelisted_for_api_key':
                return 'Delta rejected account access: this computer\'s public IP is not whitelisted for the API key.'
            if response.status_code == 401:
                return 'Delta rejected authentication. Verify Testnet credentials, permissions and system clock.'
            if response.status_code == 429:
                return 'Delta rate limit reached. Account data will retry on the next refresh.'
        except (ValueError, AttributeError):
            pass
    return 'Account data unavailable. Check Testnet credentials, permissions and connectivity.'
