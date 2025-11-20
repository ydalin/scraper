# trade.py – FINAL ×10 EXECUTION – CORRECT SYMBOL FORMAT SYMBOLUSDT
from api import bingx_api_request

async def execute_trade(client, signal, usdt_amount, leverage=10, config=None, dry_run=False):
    if config is None:
        from config import get_config
        config = get_config()

    # FIX: BingX now requires SYMBOLUSDT (no slash, no dash)
    symbol = signal['symbol'].replace('/', '').replace('-', '').upper()  # BTC/USDT → BTCUSDT

    direction = signal['direction']
    entry = signal['entry']
    targets = signal['targets']
    stoploss = signal['stoploss']

    if dry_run:
        print(f"[DRY RUN] Would open {direction} {symbol} {leverage}x ${usdt_amount:.2f}")
        return

    qty = round((usdt_amount * leverage) / entry, 6)

    # Set leverage & isolated mode
    await bingx_api_request('POST', '/openApi/swap/v2/trade/leverage', client['api_key'], client['secret_key'], data={
        'symbol': symbol, 'side': 'BOTH', 'leverage': leverage
    })
    await bingx_api_request('POST', '/openApi/swap/v2/trade/marginType', client['api_key'], client['secret_key'], data={
        'symbol': symbol, 'marginType': 'ISOLATED'
    })

    # Entry order
    side = 'BUY' if direction == 'LONG' else 'SELL'
    opposite = 'SELL' if direction == 'LONG' else 'BUY'

    entry_payload = {
        'symbol': symbol,
        'side': side,
        'positionSide': 'BOTH',
        'type': 'LIMIT',
        'quantity': f"{qty:.6f}",
        'price': str(entry),
        'timeInForce': 'GTC',
        'workingType': 'MARK_PRICE'
    }
    print(f"SENDING ENTRY ORDER: {entry_payload}")
    entry_resp = await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], data=entry_payload)
    print(f"ENTRY RESPONSE: {entry_resp}")

    # 4 Take Profits
    closed = 0.0
    for i, tp in enumerate(targets):
        percent = [config['tp1_close_percent'], config['tp2_close_percent'], config['tp3_close_percent'], config['tp4_close_percent']][i]
        tp_qty = qty * (percent / 100)
        closed += percent

        tp_payload = {
            'symbol': symbol,
            'side': opposite,
            'positionSide': 'BOTH',
            'type': 'TAKE_PROFIT_MARKET',
            'quantity': f"{tp_qty:.6f}",
            'stopPrice': str(tp),
            'workingType': 'MARK_PRICE',
            'reduceOnly': 'false'
        }
        await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], data=tp_payload)

    # Trailing Stop on remaining
    remaining_qty = qty * (100 - closed) / 100
    if remaining_qty > 0:
        trail_payload = {
            'symbol': symbol,
            'side': opposite,
            'positionSide': 'BOTH',
            'type': 'TRAILING_STOP_MARKET',
            'quantity': f"{remaining_qty:.6f}",
            'callbackRate': str(config['trailing_callback_rate']),
            'workingType': 'MARK_PRICE',
            'reduceOnly': 'false'
        }
        await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], data=trail_payload)
        print("TRAILING STOP PLACED ON REMAINING RUNNER")

    # Stop Loss
    sl_payload = {
        'symbol': symbol,
        'side': opposite,
        'positionSide': 'BOTH',
        'type': 'STOP_MARKET',
        'quantity': f"{qty:.6f}",
        'stopPrice': str(stoploss),
        'workingType': 'MARK_PRICE',
        'reduceOnly': 'false'
    }
    await bingx_api_request('POST', '/openApi/swap/v2/trade/order', client['api_key'], client['secret_key'], data=sl_payload)

    print(f"REAL TRADE EXECUTED: {symbol} {direction} {leverage}x – ${usdt_amount:.2f}")