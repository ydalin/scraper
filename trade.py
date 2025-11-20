# trade.py – SYMBOL-USDT, hedge-mode safe, trailing stop + reduceOnly on all exits
from api import bingx_api_request


async def execute_trade(client, signal, usdt_amount, leverage=10, config=None, dry_run=False):
    """Execute a trade on BingX based on a parsed signal.

    client: dict with 'api_key' and 'secret_key'
    signal: dict with keys: symbol, direction ('LONG'/'SHORT'), entry (float),
            targets (list[float]), stoploss (float)
    usdt_amount: how many USDT to allocate (not notional after leverage)
    leverage: leverage multiplier
    config: optional config dict (if None, loaded from config.get_config())
    dry_run: if True, no orders are sent regardless of config.dry_run_mode
    """
    if config is None:
        from config import get_config
        config = get_config()

    # Effective dry-run: either explicit or via config flag
    effective_dry_run = dry_run or config.get("dry_run_mode", False)

    # BingX uses AAA-BBB format for symbols (e.g. BTC-USDT)
    # parse_signal gives e.g. "BTC/USDT"
    symbol = signal["symbol"].upper().replace("/", "-")

    direction = signal["direction"].upper()   # LONG / SHORT
    entry = float(signal["entry"])
    targets = [float(t) for t in signal["targets"]]
    stoploss = float(signal["stoploss"])

    # side = action (BUY/SELL), positionSide = LONG/SHORT (hedge mode)
    side = "BUY" if direction == "LONG" else "SELL"
    opposite = "SELL" if direction == "LONG" else "BUY"
    position_side = "LONG" if direction == "LONG" else "SHORT"

    if effective_dry_run:
        print(f"[DRY RUN] Would open {direction} {symbol} {leverage}x with ${usdt_amount:.2f}")
        print(f"  Entry: {entry}, Targets: {targets}, Stop: {stoploss}")
        return

    # Position size in base asset
    qty = round((usdt_amount * leverage) / entry, 6)

    # Set leverage & isolated mode
    await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/leverage",
        client["api_key"],
        client["secret_key"],
        data={"symbol": symbol, "side": "BOTH", "leverage": leverage},
    )
    await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/marginType",
        client["api_key"],
        client["secret_key"],
        data={"symbol": symbol, "marginType": "ISOLATED"},
    )

    # ---------------- ENTRY ORDER ----------------
    entry_payload = {
        "symbol": symbol,               # e.g. BTC-USDT
        "side": side,                   # BUY / SELL
        "positionSide": position_side,  # LONG / SHORT (required in hedge mode)
        "type": "LIMIT",
        "quantity": f"{qty:.6f}",
        "price": str(entry),
        "timeInForce": "GTC",
        "workingType": "MARK_PRICE",
    }
    print("ENTRY ORDER:", entry_payload)
    entry_resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        data=entry_payload,
    )
    print("ENTRY RESPONSE:", entry_resp)

    # If entry failed, stop here
    if entry_resp.get("code") != 0:
        print("ENTRY FAILED, aborting TPs/SL/trailing.")
        return

    # ---------------- TAKE PROFITS ----------------
    tp_percents = [
        config.get("tp1_close_percent", 0),
        config.get("tp2_close_percent", 0),
        config.get("tp3_close_percent", 0),
        config.get("tp4_close_percent", 0),
    ]

    total_tp_perc = 0.0
    for i, tp_price in enumerate(targets[:4]):
        percent = float(tp_percents[i]) if i < len(tp_percents) else 0.0
        if percent <= 0:
            continue
        total_tp_perc += percent
        tp_qty = round(qty * (percent / 100.0), 6)

        tp_payload = {
            "symbol": symbol,
            "side": opposite,
            "positionSide": position_side,
            "type": "TAKE_PROFIT_MARKET",
            "quantity": f"{tp_qty:.6f}",
            "stopPrice": str(tp_price),
            "workingType": "MARK_PRICE",
            "reduceOnly": "true",  # close-only
        }
        print(f"TP{i+1} ORDER:", tp_payload)
        tp_resp = await bingx_api_request(
            "POST",
            "/openApi/swap/v2/trade/order",
            client["api_key"],
            client["secret_key"],
            data=tp_payload,
        )
        print(f"TP{i+1} RESPONSE:", tp_resp)

    # ---------------- TRAILING STOP (optional) ----------------
    trailing_mode = config.get("trailing_stop_mode", "from_tp")

    if trailing_mode != "none":
        # Remaining percentage after all TPs (if sum < 100)
        remaining_pct = max(0.0, 100.0 - float(total_tp_perc))
        if remaining_pct > 0:
            trailing_qty = round(qty * (remaining_pct / 100.0), 6)

            # Decide activation price
            if trailing_mode == "from_tp":
                tp_index = int(config.get("trailing_activate_after_tp", 4))
                tp_index = max(1, min(4, tp_index))
                idx = min(tp_index - 1, len(targets) - 1)
                activation = targets[idx]
            elif trailing_mode == "from_entry":
                activation = entry
            else:
                print(f"Unknown trailing_stop_mode={trailing_mode}, skipping trailing stop.")
                activation = None

            if activation is not None:
                trail_payload = {
                    "symbol": symbol,
                    "side": opposite,
                    "positionSide": position_side,
                    "quantity": f"{trailing_qty:.6f}",

                    # BingX trailing parameters
                    "callbackRate": str(config.get("trailing_callback_rate", 0.5) / 100),
                    # e.g. config 1.3 → 0.013 (1.3%)

                    "activationPrice": str(activation),

                    "type": "TRAILING_STOP_MARKET",
                    "workingType": "MARK_PRICE",
                    "reduceOnly": "true",
                }

                print(f"TRAILING STOP ({trailing_mode}) ORDER:", trail_payload)

                trail_resp = await bingx_api_request(
                    "POST",
                    "/openApi/swap/v2/trade/order/trailingStop",
                    client["api_key"],
                    client["secret_key"],
                    data=trail_payload,
                )

                print("TRAILING STOP RESPONSE:", trail_resp)

        else:
            print("No remaining quantity for trailing stop (TP percents sum to 100 or more).")
    else:
        print("Trailing stop disabled by config (trailing_stop_mode='none').")

    # ---------------- STOP LOSS ----------------
    sl_payload = {
        "symbol": symbol,
        "side": opposite,
        "positionSide": position_side,
        "type": "STOP_MARKET",
        "quantity": f"{qty:.6f}",
        "stopPrice": str(stoploss),
        "workingType": "MARK_PRICE",
        "reduceOnly": "true",
    }
    print("STOP LOSS ORDER:", sl_payload)
    sl_resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        data=sl_payload,
    )
    print("STOP LOSS RESPONSE:", sl_resp)

    print(f"REAL TRADE EXECUTED: {symbol} {direction} {leverage}x – ${usdt_amount:.2f}")
