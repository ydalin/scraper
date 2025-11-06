# trade.py – FIXED: set leverage first
import asyncio
from api import bingx_api_request

MAX_POSITION_VALUE = 25000.0

async def execute_trade(client, signal, usdt_amount, dry_run, custom_leverage):
    symbol = signal['symbol'].replace('-PERP', '-USDT')
    side = 'BUY' if signal['direction'] == 'LONG' else 'SELL'
    position_side = signal['direction']
    leverage = custom_leverage
    entry = signal['entry']

    qty = (usdt_amount * leverage) / entry
    position_value = usdt_amount * leverage

    # === SET LEVERAGE FIRST ===
    try:
        await bingx_api_request('POST', '/openApi/swap/v2/trade/leverage', client['api_key'], client['secret_key'], client['base_url'],
                                data={'symbol': symbol, 'leverage': leverage, 'openType': 'cross'})
        print(f"Leverage set to {leverage}x")
    except Exception as e:
        print(f"Leverage set failed: {e}")

    # === CHECK EXISTING POSITION ===
    try:
        pos = await bingx_api_request('GET', '/openApi/swap/v2/trade/position', client['api_key'], client['secret_key'], client['base_url'],
                                       params={'symbol': symbol})
        if pos.get('data'):
            existing_value = abs(float(pos['data'][0]['positionAmt'])) * float(pos['data'][0]['markPrice'])
            total_value = existing_value + position_value
            if total_value > MAX_POSITION_VALUE:
                print(f"Position limit exceeded: {total_value:.2f} > {MAX_POSITION_VALUE} USDT")
                return
    except Exception as e:
        print(f"Position check failed: {e}")
        return

    # Open position
    order = await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], client['base_url'],
                                    data={
                                        'symbol': symbol,
                                        'side': side,
                                        'positionSide': position_side,
                                        'type': 'MARKET',
                                        'quantity': f"{qty:.6f}",
                                        'leverage': leverage
                                    })
    if order.get('code') != 0:
        print(f"Order failed: {order.get('msg')}")
        return
    order_id = order['data']['order']['orderId']
    print(f"Order placed: {order_id}")

    # Set TP1–T4
    for tp in signal['targets']:
        await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], client['base_url'],
                                data={'symbol': symbol, 'orderId': order_id, 'stopPrice': tp, 'type': 'TAKE_PROFIT_MARKET'})

    # Set SL
    sl_resp = await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], client['base_url'],
                                      data={'symbol': symbol, 'orderId': order_id, 'stopPrice': signal['stoploss'], 'type': 'STOP_MARKET'})
    sl_order_id = sl_resp['data']['order']['orderId']

    # Monitor
    while True:
        await asyncio.sleep(10)
        pos = await bingx_api_request('GET', '/openApi/swap/v2/trade/position', client['api_key'], client['secret_key'], client['base_url'],
                                       params={'symbol': symbol})
        if pos.get('data'):
            pnl = float(pos['data'][0]['unrealisedPnl'])
            if pnl >= 200:
                await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], client['base_url'],
                                         data={'symbol': symbol, 'orderId': sl_order_id, 'stopPrice': entry, 'type': 'STOP_MARKET'})
                break
            if pnl >= 100:
                await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], client['base_url'],
                                         data={'symbol': symbol, 'side': 'CLOSE', 'type': 'MARKET', 'quantity': f"{qty * 0.75:.6f}"})
                released_usdt = usdt_amount * 0.75
                await execute_trade(client, signal, released_usdt, dry_run, custom_leverage)
                break