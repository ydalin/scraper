import math
from api import bingx_api_request


def format_qty(qty):
    """Formats quantity with up to 6 decimals (common for futures)."""
    return f"{qty:.6f}".rstrip("0").rstrip(".")


async def execute_trade(client, signal, usdt_amount, leverage=10,
                        config=None, dry_run=False):
    api_key = client["api_key"]
    secret_key = client["secret_key"]

    symbol = signal["symbol"].replace("/", "-")
    direction = signal["direction"].upper()
    entry_price = float(signal["entry"])
    stop_loss = float(signal["stoploss"])

    qty = (usdt_amount * leverage) / entry_price
    qty_str = format_qty(qty)

    position_side = "BOTH"

    if direction == "LONG":
        entry_side = "BUY"
        exit_side = "SELL"
    else:
        entry_side = "SELL"
        exit_side = "BUY"

    entry_order = {
        "symbol": symbol,
        "side": entry_side,
        "positionSide": position_side,
        "type": "LIMIT",
        "quantity": qty_str,
        "price": str(entry_price),
        "timeInForce": "GTC",
        "workingType": "MARK_PRICE",
    }

    print(f"ENTRY ORDER: {entry_order}")

    if dry_run:
        print("DRY RUN → Entry not sent.")
        return

    entry_response = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        api_key,
        secret_key,
        entry_order,
    )
    print(f"ENTRY RESPONSE: {entry_response}")

    if entry_response.get("code") != 0:
        print("ENTRY FAILED, aborting TPs/SL/trailing.")
        return

    tp1_pct = float(config["tp1_close_percent"])
    tp2_pct = float(config["tp2_close_percent"])
    tp3_pct = float(config["tp3_close_percent"])
    tp4_pct = float(config["tp4_close_percent"])

    def pct_qty(p):
        return format_qty(qty * p / 100)

    tp1_qty = pct_qty(tp1_pct)
    tp2_qty = pct_qty(tp2_pct)
    tp3_qty = pct_qty(tp3_pct)
    tp4_qty = pct_qty(tp4_pct)

    tp_prices = signal["targets"]

    for idx, (tp_price, tp_qty) in enumerate(
        [
            (tp_prices[0], tp1_qty),
            (tp_prices[1], tp2_qty),
            (tp_prices[2], tp3_qty),
            (tp_prices[3], tp4_qty),
        ],
        start=1,
    ):
        tp_order = {
            "symbol": symbol,
            "side": exit_side,
            "positionSide": position_side,
            "type": "TAKE_PROFIT_MARKET",
            "quantity": tp_qty,
            "stopPrice": str(tp_price),
            "workingType": "MARK_PRICE",
        }

        print(f"TP{idx} ORDER: {tp_order}")

        if dry_run:
            print(f"DRY RUN → TP{idx} not sent.")
            continue

        tp_res = await bingx_api_request(
            "POST",
            "/openApi/swap/v2/trade/order",
            api_key,
            secret_key,
            tp_order,
        )
        print(f"TP{idx} RESPONSE: {tp_res}")

    trailing_tp = int(config["trailing_activate_after_tp"])
    callback_rate = float(config["trailing_callback_rate"]) / 100.0

    if trailing_tp in (1, 2, 3, 4):
        used_pct = tp1_pct + tp2_pct + tp3_pct + tp4_pct
        remain_pct = max(0, 100 - used_pct)

        if remain_pct > 0:
            trail_qty = qty * remain_pct / 100
            trail_qty_str = format_qty(trail_qty)

            activation_price = tp_prices[trailing_tp - 1]

            trail_order = {
                "symbol": symbol,
                "side": exit_side,
                "positionSide": position_side,
                "type": "TRAILING_STOP_MARKET",
                "quantity": trail_qty_str,
                "activationPrice": str(activation_price),
                "callbackRate": str(callback_rate),
                "workingType": "MARK_PRICE",
            }

            print(f"TRAILING STOP ORDER: {trail_order}")

            if not dry_run:
                trail_res = await bingx_api_request(
                    "POST",
                    "/openApi/swap/v2/trade/order",
                    api_key,
                    secret_key,
                    trail_order,
                )
                print(f"TRAILING RESPONSE: {trail_res}")
        else:
            print("No remaining quantity for trailing stop.")
    else:
        print("Trailing stop disabled (invalid TP index).")

    sl_order = {
        "symbol": symbol,
        "side": exit_side,
        "positionSide": position_side,
        "type": "STOP_MARKET",
        "quantity": qty_str,
        "stopPrice": str(stop_loss),
        "workingType": "MARK_PRICE",
    }

    print(f"STOP LOSS ORDER: {sl_order}")

    if not dry_run:
        sl_res = await bingx_api_request(
            "POST",
            "/openApi/swap/v2/trade/order",
            api_key,
            secret_key,
            sl_order,
        )
        print(f"STOP LOSS RESPONSE: {sl_res}")

    print(
        f"REAL TRADE EXECUTED: {symbol} {direction} {leverage}x – ${usdt_amount:.2f}"
    )
