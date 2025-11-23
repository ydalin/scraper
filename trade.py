# trade.py – FINAL: No polling, correct BTC-USDT, server-side conditionals
import asyncio
from api import bingx_api_request

def format_qty(qty):
    return f"{qty:.6f}".rstrip("0").rstrip(".")

async def execute_trade(client, signal, usdt_amount, leverage=10, config=None, dry_run=False):
    if config is None:
        from config import get_config
        config = get_config()

    raw_symbol = signal.get("symbol", "").strip()
    # Convert BTC/USDT, BTCUSDT, btc-usdt → BTC-USDT
    symbol = raw_symbol.upper().replace("/", "-")
    if "USDT" in symbol and "-" not in symbol:
        symbol = symbol.replace("USDT", "-USDT")
    symbol = symbol.upper()

    direction = signal["direction"].upper()
    entry = signal["entry"]
    targets = signal["targets"]
    stoploss = signal["stoploss"]

    qty = (usdt_amount * leverage) / entry
    qty_str = format_qty(qty)

    side = "BUY" if direction == "LONG" else "SELL"
    opposite = "SELL" if direction == "LONG" else "BUY"

    print("======================================================================")
    print(f"EXECUTING: {symbol} {direction} {leverage}x – ${usdt_amount:.2f}")
    print(f"Entry: {entry} | Qty: {qty_str} | SL: {stoploss} | TPs: {targets}")
    print("======================================================================")

    if dry_run or config.get("dry_run_mode", False):
        print("[DRY RUN] Skipping real orders.")
        return

    # ENTRY ORDER
    entry_payload = {
        "symbol": symbol,
        "side": side,
        "positionSide": "BOTH",
        "type": config["order_type"],
        "quantity": qty_str,
        "price": str(entry) if config["order_type"] == "LIMIT" else None,
        "timeInForce": "GTC" if config["order_type"] == "LIMIT" else None,
        "workingType": "MARK_PRICE",
        "leverage": str(leverage),
    }
    entry_payload = {k: v for k, v in entry_payload.items() if v is not None}

    entry_resp = await bingx_api_request("POST", "/openApi/swap/v2/trade/order", client["api_key"], client["secret_key"], entry_payload)
    print(f"ENTRY: {entry_resp.get('msg', 'OK')}")

    if entry_resp.get("code") != 0:
        return

    # TAKE PROFITS
    percents = [config["tp1_close_percent"], config["tp2_close_percent"], config["tp3_close_percent"], config["tp4_close_percent"]]
    for i, (price, pct) in enumerate(zip(targets, percents), 1):
        if pct <= 0: continue
        tp_qty = format_qty(qty * pct / 100)
        tp_payload = {
            "symbol": symbol,
            "side": opposite,
            "positionSide": "BOTH",
            "type": "TAKE_PROFIT",
            "quantity": tp_qty,
            "stopPrice": str(price),
            "price": str(price),
            "workingType": "MARK_PRICE",
        }
        await bingx_api_request("POST", "/openApi/swap/v2/trade/order", client["api_key"], client["secret_key"], tp_payload)

    # TRAILING STOP
    trail_idx = config["trailing_activate_after_tp"]
    trail_rate = max(0.01, min(config["trailing_callback_rate"], 0.1))
    if 1 <= trail_idx <= len(targets):
        act_price = targets[trail_idx - 1]
        trail_payload = {
            "symbol": symbol,
            "side": opposite,
            "positionSide": "BOTH",
            "type": "TRAILING_STOP_MARKET",
            "quantity": qty_str,
            "activationPrice": str(act_price),
            "priceRate": str(trail_rate),
            "workingType": "MARK_PRICE",
        }
        await bingx_api_request("POST", "/openApi/swap/v2/trade/order", client["api_key"], client["secret_key"], trail_payload)

    # STOP LOSS
    sl_price = stoploss
    if direction == "LONG" and sl_price >= entry:
        sl_price = entry * (1 - config["stop_loss_percent"] / 100)
    if direction == "SHORT" and sl_price <= entry:
        sl_price = entry * (1 + config["stop_loss_percent"] / 100)

    sl_payload = {
        "symbol": symbol,
        "side": opposite,
        "positionSide": "BOTH",
        "type": "STOP_MARKET",
        "quantity": qty_str,
        "stopPrice": str(sl_price),
        "workingType": "MARK_PRICE",
    }
    sl_resp = await bingx_api_request("POST", "/openApi/swap/v2/trade/order", client["api_key"], client["secret_key"], sl_payload)
    if sl_resp.get("code") != 0:
        # Auto-widen on failure
        widen = config["stop_loss_percent"] * 2
        new_sl = entry * (1 - widen / 100) if direction == "LONG" else entry * (1 + widen / 100)
        sl_payload["stopPrice"] = str(new_sl)
        await bingx_api_request("POST", "/openApi/swap/v2/trade/order", client["api_key"], client["secret_key"], sl_payload)

    print(f"ALL ORDERS PLACED – {symbol} {direction}")