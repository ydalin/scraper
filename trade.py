# trade.py – FINAL: TP/SL WITH positionSide + NO PARAMS ERROR
import asyncio
from api import bingx_api_request

def print_payload(title, data):
    print(f"\n{title} PAYLOAD TO BINGX:")
    for k, v in data.items():
        print(f"  {k}: {v}")
    print("-" * 50)

async def execute_trade(client, signal, usdt_amount, dry_run, custom_leverage):
    symbol = signal['symbol'].replace('/', '-')
    side = 'BUY' if signal['direction'] == 'LONG' else 'SELL'
    opposite_side = 'SELL' if signal['direction'] == 'LONG' else 'BUY'
    position_side = signal['direction']  # LONG or SHORT
    leverage = custom_leverage
    entry = signal['entry']
    qty = (usdt_amount * leverage) / entry

    # === DRY-RUN: FULL DETAILS ===
    if dry_run:
        print("\n" + "="*70)
        print("DRY-RUN TRADE SIMULATION")
        print("="*70)
        print(f"Symbol:       {symbol}")
        print(f"Direction:    {signal['direction']} ({side})")
        print(f"Leverage:     {leverage}x")
        print(f"Entry:        {entry}")
        print(f"Quantity:     {qty:.6f}")
        print(f"Position $:   {usdt_amount * leverage:.2f} USDT")
        print(f"Take Profits: {signal['targets']}")
        print(f"Stop Loss:    {signal['stoploss']}")
        rr = (signal['targets'][-1] - entry) / (entry - signal['stoploss'])
        print(f"Risk/Reward:  {rr:.2f}:1 (to final TP)")
        print("="*70 + "\n")
        return

    # === ENTRY ORDER ===
    entry_payload = {
        'symbol': symbol,
        'side': side,
        'positionSide': position_side,
        'type': 'MARKET',
        'quantity': f"{qty:.6f}",
        'leverage': leverage
    }
    print_payload("ENTRY ORDER", entry_payload)

    order = await bingx_api_request(
        'POST', '/openApi/swap/v2/trade/order',
        client['api_key'], client['secret_key'], client['base_url'],
        data=entry_payload
    )

    if order.get('code') != 0:
        print(f"ENTRY FAILED: {order.get('msg')}")
        return

    order_id = order.get('data', {}).get('order', {}).get('orderId')
    if not order_id:
        print("ENTRY: No orderId in response")
        return
    print(f"ENTRY SUCCESS: Order ID = {order_id}")

    # === TAKE PROFIT ORDERS (25% each) ===
    tp_qty = qty * 0.25
    for i, tp in enumerate(signal['targets'], 1):
        tp_payload = {
            'symbol': symbol,
            'side': opposite_side,
            'positionSide': position_side,  # ← FIXED: Required
            'type': 'TAKE_PROFIT_MARKET',
            'quantity': f"{tp_qty:.6f}",
            'stopPrice': tp,
            'workingType': 'MARK_PRICE'
        }
        print_payload(f"TAKE PROFIT #{i}", tp_payload)

        tp_resp = await bingx_api_request(
            'POST', '/openApi/swap/v2/trade/order',
            client['api_key'], client['secret_key'], client['base_url'],
            data=tp_payload
        )
        if tp_resp.get('code') == 0:
            tp_id = tp_resp.get('data', {}).get('order', {}).get('orderId')
            print(f"TP #{i} SET: ID = {tp_id}")
        else:
            print(f"TP #{i} FAILED: {tp_resp.get('msg')}")

    # === STOP LOSS ===
    sl_payload = {
        'symbol': symbol,
        'side': opposite_side,
        'positionSide': position_side,  # ← FIXED: Required
        'type': 'STOP_MARKET',
        'quantity': f"{qty:.6f}",
        'stopPrice': signal['stoploss'],
        'workingType': 'MARK_PRICE'
    }
    print_payload("STOP LOSS", sl_payload)

    sl_resp = await bingx_api_request(
        'POST', '/openApi/swap/v2/trade/order',
        client['api_key'], client['secret_key'], client['base_url'],
        data=sl_payload
    )
    if sl_resp.get('code') == 0:
        sl_id = sl_resp.get('data', {}).get('order', {}).get('orderId')
        print(f"SL SET: ID = {sl_id}")
    else:
        print(f"SL FAILED: {sl_resp.get('msg')}")

    # === MONITOR PnL (NO PARAMS CONFLICT) ===
    print("\nMonitoring position... (Ctrl+C to stop)")
    try:
        while True:
            await asyncio.sleep(10)
            pos = await bingx_api_request(
                'GET', '/openApi/swap/v2/trade/position',
                client['api_key'], client['secret_key'], client['base_url'],
                params={'symbol': symbol}  # ← Correct: uses params
            )
            if pos.get('data'):
                pnl = float(pos['data'][0]['unrealisedPnl'])
                print(f"Current PnL: {pnl:.4f} USDT")
    except KeyboardInterrupt:
        print("\nMonitoring stopped")