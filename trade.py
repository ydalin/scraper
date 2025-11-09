# trade.py
import asyncio
from api import bingx_api_request

async def execute_trade(client, signal, usdt_amount, dry_run, custom_leverage):
    symbol = signal['symbol']
    side = 'BUY' if signal['direction'] == 'LONG' else 'SELL'
    leverage = custom_leverage
    entry = signal['entry']

    qty = (usdt_amount * leverage) / entry

    # Open position
    order = await bingx_api_request('POST', '/openApi/swap/v2/order/create', client['api_key'], client['secret_key'], client['base_url'],
                                    data={'symbol': symbol, 'side': side, 'type': 'MARKET', 'quantity': qty, 'leverage': leverage})
    if order.get('code') != 0:
        return
    order_id = order['data']['order']['orderId']

    # Set TP1–T4
    for tp in signal['targets']:
        await bingx_api_request('POST', '/openApi/swap/v2/order/createTP', client['api_key'], client['secret_key'], client['base_url'],
                                data={'symbol': symbol, 'orderId': order_id, 'stopPrice': tp})

    # Set SL
    sl_resp = await bingx_api_request('POST', '/openApi/swap/v2/order/createSL', client['api_key'], client['secret_key'], client['base_url'],
                                      data={'symbol': symbol, 'orderId': order_id, 'stopPrice': signal['stoploss']})
    sl_order_id = sl_resp['data']['order']['orderId']

    # Monitor TP2 → Move SL
    while True:
        await asyncio.sleep(10)
        pos = await bingx_api_request('GET', '/openApi/swap/v2/trade/position', client['api_key'], client['secret_key'], client['base_url'],
                                       params={'symbol': symbol})
        if pos.get('data'):
            pnl = float(pos['data'][0]['unrealisedPnl'])
            if pnl >= 200:  # TP2
                await bingx_api_request('POST', '/openApi/swap/v2/order/modifySL', client['api_key'], client['secret_key'], client['base_url'],
                                         data={'symbol': symbol, 'orderId': sl_order_id, 'stopPrice': entry})
                break
            if pnl >= 400:  # T4
                await bingx_api_request('POST', '/openApi/swap/v2/order/create', client['api_key'], client['secret_key'], client['base_url'],
                                         data={'symbol': symbol, 'side': 'CLOSE', 'type': 'MARKET', 'quantity': qty * 0.75})
                break