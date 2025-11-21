# trade.py – LIMIT entry with timeout + cancel + TP/SL/trailing
import asyncio
import time
from api import bingx_api_request


def format_qty(qty: float) -> str:
    """Format quantity with up to 6 decimals, strip trailing zeros."""
    return f"{qty:.6f}".rstrip("0").rstrip(".")


async def _get_position_size(client, symbol: str) -> float:
    """
    Query current position size for a symbol.
    Returns absolute size (>=0), or 0.0 if none.
    """
    symbol = symbol.upper()
    resp = await bingx_api_request(
        "GET",
        "/openApi/swap/v2/trade/position",
        client["api_key"],
        client["secret_key"],
        params={"symbol": symbol},
    )

    if resp.get("code") != 0:
        return 0.0

    data = resp.get("data") or []
    if isinstance(data, dict):
        positions = [data]
    else:
        positions = data

    for pos in positions:
        if str(pos.get("symbol", "")).upper() != symbol:
            continue

        size = 0.0
        for key in (
            "positionAmt",
            "positionAmount",
            "position",
            "size",
            "quantity",
            "volume",
            "availableQty",
        ):
            if key in pos:
                try:
                    size = float(pos[key])
                    break
                except Exception:
                    continue

        if size != 0:
            return abs(size)

    return 0.0


async def _wait_for_fill_with_deadline(
    client,
    symbol: str,
    intended_qty: float,
    threshold: float,
    timeout: int,
    poll_interval: int = 2,
) -> float:
    """
    Wait until |position_size| >= threshold * intended_qty, or timeout.
    Returns the *last seen* position size (may be 0 if nothing filled).
    """
    start = time.time()
    last_size = 0.0
    print(
        f"[WAIT] Waiting for near-full fill on {symbol}: "
        f">= {threshold * 100:.1f}% of {intended_qty:.6f} (timeout {timeout}s)"
    )

    while time.time() - start < timeout:
        size = await _get_position_size(client, symbol)
        last_size = size
        if size >= intended_qty * threshold:
            print(
                f"[WAIT] Position near-full: size={size:.6f} "
                f"(intended={intended_qty:.6f})"
            )
            return size

        await asyncio.sleep(poll_interval)

    print(
        f"[WAIT] Near-full fill not reached for {symbol} within {timeout}s. "
        f"Last size={last_size:.6f}"
    )
    return last_size


async def _cancel_order(client, symbol: str, order_id):
    """Cancel a specific order by symbol + orderId."""
    payload = {
        "symbol": symbol.upper(),
        "orderId": str(order_id),
    }
    print(f"[CANCEL] Canceling order {order_id} for {symbol} with payload: {payload}")
    resp = await bingx_api_request(
        "DELETE",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        params=payload,
    )
    print(f"[CANCEL] RESPONSE: {resp}")
    return resp


async def _close_position_market(client, symbol: str, direction: str, qty: float):
    """
    Close an existing position at market for a given size.
    direction: 'LONG'/'SHORT' for the *original* position direction.
    """
    if qty <= 0:
        return

    symbol = symbol.upper()
    close_side = "SELL" if direction.upper() == "LONG" else "BUY"
    qty_str = format_qty(qty)

    payload = {
        "symbol": symbol,
        "side": close_side,
        "positionSide": "BOTH",
        "type": "MARKET",
        "quantity": qty_str,
        "workingType": "MARK_PRICE",
    }
    print(f"[CLOSE] Closing partial position at MARKET: {payload}")
    resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        params=payload,
    )
    print(f"[CLOSE] RESPONSE: {resp}")
    return resp


async def execute_trade(client, signal, usdt_amount, leverage=10, config=None, dry_run=False):
    """
    Execute a trade based on a Telegram signal.

    - Uses MARKET or LIMIT based on config["order_type"].
    - If LIMIT:
        * place limit entry
        * wait up to limit_fill_timeout_seconds for near-full fill
        * if not filled enough: cancel order, close any partial at market, stop.
        * if filled enough: place TP/SL/trailing normally.
    - If MARKET: place TP/SL/trailing immediately (no polling).
    """
    if config is None:
        from config import get_config
        config = get_config()

    symbol = signal["symbol"].upper().replace("/", "-")
    direction = signal["direction"].upper()  # LONG / SHORT
    entry = float(signal["entry"])
    targets = [float(t) for t in signal["targets"][:4]]
    stoploss = float(signal["stoploss"])

    # Position size from USDT, leverage, entry
    qty = (usdt_amount * leverage) / entry
    qty_str = format_qty(qty)

    side = "BUY" if direction == "LONG" else "SELL"
    opposite = "SELL" if direction == "LONG" else "BUY"

    # Entry order type from config
    order_type = str(config.get("order_type", "MARKET")).upper()
    if order_type not in ("MARKET", "LIMIT"):
        order_type = "MARKET"

    # LIMIT fill behavior from config (with defaults)
    fill_threshold = float(config.get("limit_fill_threshold", 0.99))  # 99% by default
    fill_timeout = int(config.get("limit_fill_timeout_seconds", 60))  # 60s default

    print("======================================================================")
    print(f"EXECUTING TRADE for {symbol}")
    print(f"  Direction:   {direction}")
    print(f"  Order type:  {order_type}")
    print(f"  Entry:       {entry}")
    print(f"  Qty (intended): {qty_str} (≈ {usdt_amount} USDT at {leverage}x)")
    print(f"  Targets:     {targets}")
    print(f"  Stoploss:    {stoploss}")
    print("======================================================================")

    # ========== ENTRY ORDER ==========
    entry_payload = {
        "symbol": symbol,
        "side": side,
        "positionSide": "BOTH",   # One-Way mode
        "type": order_type,
        "quantity": qty_str,
        "workingType": "MARK_PRICE",
        "leverage": leverage,
    }
    if order_type == "LIMIT":
        entry_payload["price"] = str(entry)
        entry_payload["timeInForce"] = "GTC"

    print(f"ENTRY ORDER: {entry_payload}")

    if dry_run or config.get("dry_run_mode", False):
        print("[DRY RUN] Skipping real entry order.")
        return

    entry_resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        params=entry_payload,
    )
    print(f"ENTRY RESPONSE: {entry_resp}")

    if entry_resp.get("code") != 0:
        print(f"[ENTRY ERROR] {entry_resp.get('msg')}")
        return

    # Extract orderId for potential cancel
    order_data = (entry_resp.get("data") or {}).get("order") or {}
    entry_order_id = order_data.get("orderId") or order_data.get("orderID")

    # Decide effective quantity:
    # - MARKET: assume full intended qty
    # - LIMIT: wait for near-full fill and use the detected size
    effective_qty = qty

    if order_type == "LIMIT":
        filled_size = await _wait_for_fill_with_deadline(
            client,
            symbol,
            qty,
            threshold=fill_threshold,
            timeout=fill_timeout,
        )

        target_size = qty * fill_threshold

        if filled_size >= target_size:
            # Good: position is filled enough
            effective_qty = filled_size
            print(
                f"[INFO] LIMIT entry sufficiently filled: {filled_size:.6f} "
                f"(>= {fill_threshold * 100:.1f}% of {qty:.6f})"
            )
        else:
            # Not filled enough within timeout: cancel order, close partial (if any), and stop
            print(
                f"[INFO] LIMIT entry NOT filled enough within timeout. "
                f"filled_size={filled_size:.6f}, needed>={target_size:.6f}"
            )
            if entry_order_id is not None:
                await _cancel_order(client, symbol, entry_order_id)

            if filled_size > 0:
                # Close any partial position at market for safety
                await _close_position_market(client, symbol, direction, filled_size)

            print("[INFO] Exiting without placing TP/SL/trailing.")
            return

    eff_qty_str = format_qty(effective_qty)
    print(f"[INFO] Using effective_qty={eff_qty_str} for exits.")

    # ========== TAKE PROFITS ==========
    tp1_pct = float(config.get("tp1_close_percent", 35.0))
    tp2_pct = float(config.get("tp2_close_percent", 30.0))
    tp3_pct = float(config.get("tp3_close_percent", 20.0))
    tp4_pct = float(config.get("tp4_close_percent", 15.0))

    tp_pcts = [tp1_pct, tp2_pct, tp3_pct, tp4_pct]

    for i, (tp_price, tp_pct) in enumerate(zip(targets, tp_pcts), start=1):
        if tp_pct <= 0:
            continue

        tp_qty = effective_qty * (tp_pct / 100.0)
        tp_qty_str = format_qty(tp_qty)

        tp_payload = {
            "symbol": symbol,
            "side": opposite,
            "positionSide": "BOTH",
            "type": "TAKE_PROFIT_MARKET",
            "quantity": tp_qty_str,
            "stopPrice": str(tp_price),
            "workingType": "MARK_PRICE",
        }

        print(f"TP{i} ORDER: {tp_payload}")

        tp_resp = await bingx_api_request(
            "POST",
            "/openApi/swap/v2/trade/order",
            client["api_key"],
            client["secret_key"],
            params=tp_payload,
        )
        print(f"TP{i} RESPONSE: {tp_resp}")

    # ========== TRAILING STOP ==========
    trail_tp_idx = int(config.get("trailing_activate_after_tp", 0))
    callback_rate = float(config.get("trailing_callback_rate", 0.0)) / 100.0

    if 1 <= trail_tp_idx <= len(targets) and callback_rate > 0:
        used_pct = tp1_pct + tp2_pct + tp3_pct + tp4_pct
        remain_pct = max(0.0, 100.0 - used_pct)

        if remain_pct > 0:
            trail_qty = effective_qty * (remain_pct / 100.0)
            trail_qty_str = format_qty(trail_qty)
            activation_price = targets[trail_tp_idx - 1]

            trail_payload = {
                "symbol": symbol,
                "side": opposite,
                "positionSide": "BOTH",
                "type": "TRAILING_STOP_MARKET",
                "quantity": trail_qty_str,
                "activationPrice": str(activation_price),
                "callbackRate": str(callback_rate),
                "workingType": "MARK_PRICE",
            }

            print(f"TRAILING STOP ORDER: {trail_payload}")

            trail_resp = await bingx_api_request(
                "POST",
                "/openApi/swap/v2/trade/order",
                client["api_key"],
                client["secret_key"],
                params=trail_payload,
            )
            print(f"TRAILING STOP RESPONSE: {trail_resp}")
        else:
            print("[TRAILING] No remaining quantity for trailing stop.")
    else:
        print("[TRAILING] Trailing stop disabled or invalid config.")

    # ========== STOP LOSS ==========
    sl_payload = {
        "symbol": symbol,
        "side": opposite,
        "positionSide": "BOTH",
        "type": "STOP_MARKET",
        "quantity": eff_qty_str,
        "stopPrice": str(stoploss),
        "workingType": "MARK_PRICE",
    }

    print(f"STOP LOSS ORDER: {sl_payload}")

    sl_resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        params=sl_payload,
    )
    print(f"STOP LOSS RESPONSE: {sl_resp}")

    print(
        f"REAL TRADE EXECUTED: {symbol} {direction} {leverage}x – "
        f"${usdt_amount:.2f} (order_type={order_type})"
    )
