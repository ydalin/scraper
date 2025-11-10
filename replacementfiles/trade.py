# trade.py – FINAL: 4 PARTIAL TP (25%) + SL + Manual Leverage & Amount
import asyncio
from api import bingx_api_request

def print_payload(title, data):
    print(f"\n{title} PAYLOAD TO BINGX:")
    for k, v in data.items():
        print(f"  {k}: {v}")
    print("-" * 50)

async def execute_trade(client, signal, usdt_amount, leverage, dry_run=False):
    symbol = signal['symbol'].replace('/', '-')
    side = 'BUY' if signal['direction'] == 'LONG' else 'SELL'
    opposite_side = 'SELL' if signal['direction'] == 'LONG' else 'BUY'
    position_side = signal['direction']
    entry = signal['entry']
    qty = (usdt_amount * leverage) / entry  # Full qty

    # === DRY-RUN ===
    if dry_run:
        print("\n" + "="*70)
        print("DRY-RUN SIMULATION")
        print("="*70)
        print(f"Symbol:       {symbol}")
        print(f"Direction:    {signal['direction']}")
        print(f"Entry:        {entry}")
        print(f"Amount:       {usdt_amount} USDT")
        print(f"Leverage:     {leverage}x")
        print(f"Quantity:     {qty:.6f}")
        print(f"Notional:     {usdt_amount * leverage:.2f} USDT")
        print(f"TPs:          {signal['targets']}")
        print(f"SL:           {signal['stoploss']}")
        print("="*70 + "\n")
        return

    # === ENTRY ORDER ===
    entry_payload = {
        'symbol': symbol,
        'side': side,
        'positionSide': position_side,
        'type': 'MARKET',
        'quantity': f"{qty:.6f}",
        'leverage': str(leverage)
    }
    print_payload("ENTRY", entry_payload)
    entry_resp = await bingx_api_request(
        'POST', '/openApi/swap/v2/trade/order',
        client['api_key'], client['secret_key'], client['base_url'],
        data=entry_payload
    )
    if entry_resp.get('code') != 0:
        print(f"ENTRY FAILED: {entry_resp.get('msg')}")
        return

    # === 4 PARTIAL TAKE PROFITS (25% each) ===
    tp_qty = qty / 4
    for i in range(4):
        tp_price = signal['targets'][i]
        tp_payload = {
            'symbol': symbol,
            'side': opposite_side,
            'positionSide': position_side,
            'type': 'LIMIT',
            'quantity': f"{tp_qty:.6f}",
            'price': str(tp_price),
            'timeInForce': 'GTC',
            'workingType': 'MARK_PRICE'
        }
        print_payload(f"TP{i+1} (25%)", tp_payload)
        tp_resp = await bingx_api_request(
            'POST', '/openApi/swap/v2/trade/order',
            client['api_key'], client['secret_key'], client['base_url'],
            data=tp_payload
        )
        if tp_resp.get('code') == 0:
            print(f"TP{i+1} SET: ID = {tp_resp.get('data', {}).get('order', {}).get('orderId')}")
        else:
            print(f"TP{i+1} FAILED: {tp_resp.get('msg')}")

    # === STOP LOSS (100%) ===
    sl_payload = {
        'symbol': symbol,
        'side': opposite_side,
        'positionSide': position_side,
        'type': 'STOP_MARKET',
        'quantity': f"{qty:.6f}",
        'stopPrice': str(signal['stoploss']),
        'workingType': 'MARK_PRICE'
    }
    print_payload("STOP LOSS", sl_payload)
    sl_resp = await bingx_api_request(
        'POST', '/openApi/swap/v2/trade/order',
        client['api_key'], client['secret_key'], client['base_url'],
        data=sl_payload
    )
    if sl_resp.get('code') == 0:
        print(f"SL SET: ID = {sl_resp.get('data', {}).get('order', {}).get('orderId')}")
    else:
        print(f"SL FAILED: {sl_resp.get('msg')}")
