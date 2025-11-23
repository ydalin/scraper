import asyncio
import time
import math
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
    try:
        resp = await bingx_api_request(
            "GET",
            "/openApi/swap/v2/trade/position",
            client["api_key"],
            client["secret_key"],
            params={"symbol": symbol},
        )
    except Exception as e:
        print(f"[POS] Error fetching position for {symbol}: {e}")
        return 0.0

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
                    return abs(float(pos[key]))
                except Exception:
                    continue
    return 0.0


async def _get_order_status(client, symbol: str, order_id: str) -> str:
    """
    Query order status for a specific order.
    Returns status string (e.g. 'NEW', 'FILLED', 'PARTIALLY_FILLED', etc.) or '' on error.
    """
    symbol = symbol.upper()
    try:
        resp = await bingx_api_request(
            "GET",
            "/openApi/swap/v2/trade/order",
            client["api_key"],
            client["secret_key"],
            params={"symbol": symbol, "orderId": str(order_id)},
        )
    except Exception as e:
        print(f"[ORDER] Error fetching order status for {symbol} {order_id}: {e}")
        return ""

    if resp.get("code") != 0:
        return ""

    data = resp.get("data") or {}
    if isinstance(data, list) and data:
        data = data[0]

    return str(data.get("status", "")).upper()


async def _wait_for_fill_hybrid(
    client,
    symbol: str,
    order_id: str,
    intended_qty: float,
    threshold: float,
    timeout: int,
    poll_interval: int = 2,
) -> float:
    """
    Hybrid wait: use BOTH order status and position size.

    We consider the entry "good enough" when:
      - position_size >= threshold * intended_qty, OR
      - order is FILLED and a non-zero position appears.

    Returns the detected position size (>=0). If zero at timeout → treat as failed.
    """
    symbol = symbol.upper()
    start = time.time()
    last_size = 0.0
    print(
        f"[WAIT] Hybrid fill check for {symbol}: "
        f"threshold={threshold*100:.1f}% of {intended_qty:.6f}, timeout={timeout}s"
    )

    while time.time() - start < timeout:
        status = await _get_order_status(client, symbol, order_id)
        if status:
            print(f"[WAIT] Order {order_id} status: {status}")

        size = await _get_position_size(client, symbol)
        last_size = size
        if size > 0:
            print(f"[WAIT] Current position size for {symbol}: {size:.6f}")

        target = intended_qty * threshold

        if size >= target and size > 0:
            print(
                f"[WAIT] Position >= threshold: size={size:.6f}, needed>={target:.6f}"
            )
            return size

        if status == "FILLED" and size > 0:
            print(
                f"[WAIT] Order FILLED and position present: "
                f"size={size:.6f}, intended={intended_qty:.6f}"
            )
            return size

        await asyncio.sleep(poll_interval)

    print(
        f"[WAIT] Hybrid fill timeout for {symbol}. "
        f"Last position size={last_size:.6f}"
    )
    return last_size


async def _cancel_all_orders_for_symbol(client, symbol: str):
    """
    Cancel ALL open orders for a given symbol.

    Uses BingX Perpetual Futures v2 endpoint:
      DELETE /openApi/swap/v2/trade/allOpenOrders
    """
    sym = symbol.upper()
    payload = {"symbol": sym}
    print(f"[CANCEL] Canceling ALL open orders for {sym} with payload: {payload}")

    resp = await bingx_api_request(
        "DELETE",
        "/openApi/swap/v2/trade/allOpenOrders",
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
        "positionSide": "BOTH",  # one-way mode
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

    - LIMIT:
        * if entry response is already FILLED → use executedQty and
          immediately place TP LIMIT / SL / trailing (NO waiting, NO cancel).
        * otherwise: place limit entry, hybrid wait up to timeout;
          if not filled enough → cancel & close partial, then exit.
    - MARKET:
        * place entry and then TP LIMIT / SL / trailing immediately.
    """
    if config is None:
        from config import get_config
        config = get_config()

    raw_symbol = signal.get("symbol", "")
    symbol = raw_symbol.upper().replace("/", "-")

    direction = str(signal.get("direction", "")).upper()  # LONG / SHORT
    entry = float(signal.get("entry", 0.0))
    targets = [float(t) for t in signal.get("targets", [])[:4]]
    stoploss = float(signal.get("stoploss", 0.0))

    if not symbol or entry <= 0 or not direction or not targets or stoploss <= 0:
        print(
            "[ERROR] Invalid signal in execute_trade: "
            f"raw_symbol={raw_symbol!r}, mapped_symbol={symbol!r}, "
            f"direction={direction!r}, entry={entry!r}, "
            f"targets={targets!r}, stoploss={stoploss!r}"
        )
        return

    qty = (usdt_amount * leverage) / entry
    qty_str = format_qty(qty)

    side = "BUY" if direction == "LONG" else "SELL"
    opposite = "SELL" if direction == "LONG" else "BUY"

    order_type = str(config.get("order_type", "MARKET")).upper()
    if order_type not in ("MARKET", "LIMIT"):
        order_type = "MARKET"

    fill_threshold = float(config.get("limit_fill_threshold", 0.01))         # 1%
    fill_timeout = int(config.get("limit_fill_timeout_seconds", 180))        # 180s

    print("======================================================================")
    print(f"EXECUTING TRADE for {symbol}")
    print(f"  Direction:   {direction}")
    print(f"  Order type:  {order_type}")
    print(f"  Entry:       {entry}")
    print(
        f"  Qty (intended): {qty_str} (≈ {usdt_amount:.4f} USDT at {leverage}x)"
    )
    print(f"  Targets:     {targets}")
    print(f"  Stoploss:    {stoploss}")
    print("======================================================================")

    # ===== ENTRY ORDER =====
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

    order_data = (entry_resp.get("data") or {}).get("order") or {}
    entry_order_id = order_data.get("orderId") or order_data.get("orderID")
    status = str(order_data.get("status", "")).upper()
    executed = order_data.get("executedQty")

    effective_qty = qty

    # === KEY FIX: if LIMIT and already FILLED, trust executedQty and SKIP waiting ===
    if order_type == "LIMIT" and status == "FILLED":
        try:
            if executed is not None:
                executed_f = float(executed)
                if executed_f > 0:
                    effective_qty = executed_f
                    print(
                        "[INFO] LIMIT entry FILLED immediately, "
                        f"using executedQty={executed_f:.6f} and placing TP/SL/trailing."
                    )
        except Exception:
            print("[WARN] Could not parse executedQty, using intended qty.")

    # Otherwise, use hybrid wait for LIMIT that is not yet filled
    elif order_type == "LIMIT":
        filled_size = await _wait_for_fill_hybrid(
            client,
            symbol,
            str(entry_order_id) if entry_order_id is not None else "",
            qty,
            threshold=fill_threshold,
            timeout=fill_timeout,
        )

        target_size = qty * fill_threshold

        if filled_size >= target_size and filled_size > 0:
            effective_qty = filled_size
            print(
                "[INFO] LIMIT entry sufficiently filled: "
                f"{filled_size:.6f} (>= {target_size:.6f})"
            )
        else:
            print(
                "[INFO] LIMIT entry NOT filled enough within timeout. "
                f"filled_size={filled_size:.6f}, needed>={target_size:.6f}"
            )
            await _cancel_all_orders_for_symbol(client, symbol)
            if filled_size > 0:
                await _close_position_market(client, symbol, direction, filled_size)
            print("[INFO] Exiting without placing TP/SL/trailing.")
            return

    else:
        # MARKET: if executedQty present, use it
        try:
            if executed is not None:
                executed_f = float(executed)
                if executed_f > 0:
                    effective_qty = executed_f
        except Exception:
            pass

    eff_qty_str = format_qty(effective_qty)
    print(f"[INFO] Using effective_qty={eff_qty_str} for exits.")

    # ===== TAKE PROFITS (LIMIT CONDITIONALS) =====
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

        # TAKE_PROFIT = conditional LIMIT
        tp_payload = {
            "symbol": symbol,
            "side": opposite,
            "positionSide": "BOTH",
            "type": "TAKE_PROFIT",
            "quantity": tp_qty_str,
            "price": str(tp_price),       # limit price
            "stopPrice": str(tp_price),   # trigger
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

    # ===== TRAILING STOP (SLIDING) – sell EVERYTHING when activated =====
    trail_tp_idx = int(config.get("trailing_activate_after_tp", 0))
    callback_rate = float(config.get("trailing_callback_rate", 0.0)) / 100.0

    if 1 <= trail_tp_idx <= len(targets) and callback_rate > 0:
        trail_qty = effective_qty          # full position
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
        print("[TRAILING] Trailing stop disabled or invalid config.")

    # ===== STOP LOSS =====
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
