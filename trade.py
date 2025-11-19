# trade.py – FINAL ×10 EXECUTION
from api import bingx_api_request

async def execute_trade(client, signal, usdt_amount, leverage=10, config=None, dry_run=False):
    if config is None:
        from config import get_config
        config = get_config()

    symbol = signal['symbol']
    direction = signal['direction']
    entry = signal['entry']
    targets = signal['targets']
    stoploss = signal['stoploss']

    if dry_run:
        print(f"[DRY RUN] Would open {direction} {symbol} {leverage}x ${usdt_amount}")
        return

    # Calculate quantity
    qty = round((usdt_amount * leverage) / entry, 6)

    # Set leverage & isolated mode
    await bingx_api_request('POST', '/openApi/swap/v2/trade/leverage', client['api_key'], client['secret_key'], data={
        'symbol': symbol, 'side': 'BOTH', 'leverage': leverage
    })
    await bingx_api_request('POST', '/openApi/swap/v2/trade/marginType', client['api_key'], client['secret_key'], data={
        'symbol': symbol, 'marginType': 'ISOLATED'
    })

    # Entry order (LIMIT at mid entry)
    side = 'BUY' if direction == 'LONG' else 'SELL'
    opposite = 'SELL' if direction == 'LONG' else 'BUY'

    await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], data={
        'symbol': symbol,
        'side': side,
        'positionSide': 'BOTH',
        'type': 'LIMIT',
        'quantity': str(qty),
        'price': str(entry),
        'timeInForce': 'GTC'
    })

    # 4 Take Profits
    closed = 0.0
    for i, tp in enumerate(targets):
        percent = [config['tp1_close_percent'], config['tp2_close_percent'], config['tp3_close_percent'], config['tp4_close_percent']][i]
        tp_qty = qty * (percent / 100)
        closed += percent

        await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], data={
            'symbol': symbol,
            'side': opposite,
            'positionSide': 'BOTH',
            'type': 'TAKE_PROFIT_MARKET',
            'quantity': str(tp_qty),
            'stopPrice': str(tp),
            'workingType': 'MARK_PRICE',
            'reduceOnly': 'false'
        })

    # Trailing Stop after TP2
    if config['trailing_activate_after_tp'] >= 2:
        remaining_qty = qty * (100 - closed) / 100
        if remaining_qty > 0:
            await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], data={
                'symbol': symbol,
                'side': opposite,
                'positionSide': 'BOTH',
                'type': 'TRAILING_STOP_MARKET',
                'quantity': str(remaining_qty),
                'callbackRate': str(config['trailing_callback_rate']),
                'workingType': 'MARK_PRICE',
                'reduceOnly': 'false'
            })

    # Stop Loss
    await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], data={
        'symbol': symbol,
        'side': opposite,
        'positionSide': 'BOTH',
        'type': 'STOP_MARKET',
        'quantity': str(qty),
        'stopPrice': str(stoploss),
        'workingType': 'MARK_PRICE',
        'reduceOnly': 'false'
    })

    print(f"TRADE EXECUTED: {symbol} {direction} {leverage}x – ${usdt_amount}")