import asyncio
import time
from api import bingx_api_request


def format_qty(qty):
    """Format quantity with up to 6 decimals, strip trailing zeros."""
    return f"{qty:.6f}".rstrip("0").rstrip(".")


async def _get_position_size(client, symbol):
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


async def _get_order_status(client, symbol, order_id):
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
    symbol,
    order_id,
    intended_qty,
    threshold,
    timeout,
    poll_interval=2,
):
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
        "[WAIT] Hybrid fill check for {sym}: threshold={thr:.1f}% of {qty:.6f}, "
        "timeout={to}s".format(
            sym=symbol,
            thr=threshold * 100.0,
            qty=intended_qty,
            to=timeout,
        )
    )

    while time.time() - start < timeout:
        status = await _get_order_status(client, symbol, order_id)
        if status:
            print("[WAIT] Order {oid} status: {st}".format(oid=order_id, st=status))

        size = await _get_position_size(client, symbol)
        last_size = size
        if size > 0:
            print(
                "[WAIT] Current position size for {sym}: {sz:.6f}".format(
                    sym=symbol, sz=size
                )
            )

        target = intended_qty * threshold

        if size >= target and size > 0:
            print(
                "[WAIT] Position >= threshold: size={sz:.6f}, needed>={tgt:.6f}".format(
                    sz=size, tgt=target
                )
            )
            return size

        if status == "FILLED" and size > 0:
            print(
                "[WAIT] Order FILLED and position present: size={sz:.6f}, "
                "intended={qty:.6f}".format(sz=size, qty=intended_qty)
            )
            return size

        await asyncio.sleep(poll_interval)

    print(
        "[WAIT] Hybrid fill timeout for {sym}. Last position size={sz:.6f}".format(
            sym=symbol, sz=last_size
        )
    )
    return last_size


async def _cancel_all_orders_for_symbol(client, symbol):
    """
    Cancel ALL open orders for a given symbol.

    Uses BingX Perpetual Futures v2 endpoint:
      DELETE /openApi/swap/v2/trade/allOpenOrders
    """
    sym = symbol.upper()
    payload = {"symbol": sym}
    print("[CANCEL] Canceling ALL open orders for {sym} with payload: {p}".format(
        sym=sym, p=payload
    ))

    resp = await bingx_api_request(
        "DELETE",
        "/openApi/swap/v2/trade/allOpenOrders",
        client["api_key"],
        client["secret_key"],
        params=payload,
    )

    print("[CANCEL] RESPONSE: {r}".format(r=resp))
    return resp


async def _close_position_market(client, symbol, direction, qty):
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
    print("[CLOSE] Closing partial position at MARKET: {p}".format(p=payload))
    resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        params=payload,
    )
    print("[CLOSE] RESPONSE: {r}".format(r=resp))
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
            "raw_symbol={rs!r}, mapped_symbol={ms!r}, "
            "direction={d!r}, entry={e!r}, targets={t!r}, stoploss={sl!r}".format(
                rs=raw_symbol,
                ms=symbol,
                d=direction,
                e=entry,
                t=targets,
                sl=stoploss,
            )
        )
        return

    qty = (usdt_amount * leverage) / entry
    qty_str = format_qty(qty)

    side = "BUY" if direction == "LONG" else "SELL"
    opposite = "SELL" if direction == "LONG" else "BUY"

    order_type = str(config.get("order_type", "MARKET")).upper()
    if order_type not in ("MARKET", "LIMIT"):
        order_type = "MARKET"

    fill_threshold = float(config.get("limit_fill_threshold", 0.01))      # 1%
    fill_timeout = int(config.get("limit_fill_timeout_seconds", 180))     # 180s

    print("======================================================================")
    print("EXECUTING TRADE for {s}".format(s=symbol))
    print("  Direction:   {d}".format(d=direction))
    print("  Order type:  {ot}".format(ot=order_type))
    print("  Entry:       {e}".format(e=entry))
    print(
        "  Qty (intended): {q} (≈ {u:.4f} USDT at {lev}x)".format(
            q=qty_str, u=usdt_amount, lev=leverage
        )
    )
    print("  Targets:     {t}".format(t=targets))
    print("  Stoploss:    {sl}".format(sl=stoploss))
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

    print("ENTRY ORDER: {p}".format(p=entry_payload))

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
    print("ENTRY RESPONSE: {r}".format(r=entry_resp))

    if entry_resp.get("code") != 0:
        print("[ENTRY ERROR] {m}".format(m=entry_resp.get("msg")))
        return

    order_data = (entry_resp.get("data") or {}).get("order") or {}
    entry_order_id = order_data.get("orderId") or order_data.get("orderID")
    status = str(order_data.get("status", "")).upper()
    executed = order_data.get("executedQty")

    effective_qty = qty

    # If LIMIT and already FILLED in response, trust executedQty and skip waiting
    if order_type == "LIMIT" and status == "FILLED":
        try:
            if executed is not None:
                executed_f = float(executed)
                if executed_f > 0:
                    effective_qty = executed_f
                    print(
                        "[INFO] LIMIT entry FILLED immediately, "
                        "using executedQty={q:.6f} and placing TP/SL/trailing.".format(
                            q=executed_f
                        )
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
                "[INFO] LIMIT entry sufficiently filled: {fs:.6f} (>= {ts:.6f})".format(
                    fs=filled_size, ts=target_size
                )
            )
        else:
            print(
                "[INFO] LIMIT entry NOT filled enough within timeout. "
                "filled_size={fs:.6f}, needed>={ts:.6f}".format(
                    fs=filled_size, ts=target_size
                )
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
    print("[INFO] Using effective_qty={q} for exits.".format(q=eff_qty_str))

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

        print("TP{idx} ORDER: {p}".format(idx=i, p=tp_payload))

        tp_resp = await bingx_api_request(
            "POST",
            "/openApi/swap/v2/trade/order",
            client["api_key"],
            client["secret_key"],
            params=tp_payload,
        )
        print("TP{idx} RESPONSE: {r}".format(idx=i, r=tp_resp))

    # ===== TRAILING STOP (SLIDING) – sell EVERYTHING when activated =====
    trail_tp_idx = int(config.get("trailing_activate_after_tp", 0))

    # Interpret config as "percent points", but BingX error says:
    #   "Must be lower than the maximum callback rate of 0.1%"
    # So we clamp to [0.01, 0.1] (0.01%–0.1%).
    raw_trail_rate = float(config.get("trailing_callback_rate", 0.0))
    if raw_trail_rate <= 0:
        trail_rate = 0.0
    else:
        trail_rate = max(0.01, min(raw_trail_rate, 0.1))

    if 1 <= trail_tp_idx <= len(targets) and trail_rate > 0:
        trail_qty = effective_qty          # full position
        trail_qty_str = format_qty(trail_qty)
        activation_price = targets[trail_tp_idx - 1]

        print(
            "[TRAILING] Using clamped priceRate={tr} (config requested {cfg})".format(
                tr=trail_rate, cfg=raw_trail_rate
            )
        )

        trail_payload = {
            "symbol": symbol,
            "side": opposite,
            "positionSide": "BOTH",
            "type": "TRAILING_STOP_MARKET",
            "quantity": trail_qty_str,          # close all
            "activationPrice": str(activation_price),
            "priceRate": str(trail_rate),       # must be <= 0.1 per BingX error
            "workingType": "MARK_PRICE",
        }

        print("TRAILING STOP ORDER: {p}".format(p=trail_payload))

        trail_resp = await bingx_api_request(
            "POST",
            "/openApi/swap/v2/trade/order",
            client["api_key"],
            client["secret_key"],
            params=trail_payload,
        )
        print("TRAILING STOP RESPONSE: {r}".format(r=trail_resp))
    else:
        print("[TRAILING] Trailing stop disabled or invalid config.")

    # ===== STOP LOSS with auto-widening =====
    sl_percent = float(config.get("stop_loss_percent", 1.8))
    raw_sl = stoploss

    # First, make sure SL is on the "correct" side relative to entry
    if direction == "LONG":
        # SL must be below entry; if not, push it below by stop_loss_percent
        if raw_sl >= entry:
            raw_sl = entry * (1.0 - sl_percent / 100.0)
    else:  # SHORT
        # SL must be above entry; if not, push it above by stop_loss_percent
        if raw_sl <= entry:
            raw_sl = entry * (1.0 + sl_percent / 100.0)

    sl_price = raw_sl

    sl_payload = {
        "symbol": symbol,
        "side": opposite,
        "positionSide": "BOTH",
        "type": "STOP_MARKET",
        "quantity": eff_qty_str,
        "stopPrice": str(sl_price),
        "workingType": "MARK_PRICE",
    }

    print("STOP LOSS ORDER: {p}".format(p=sl_payload))

    sl_resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        params=sl_payload,
    )
    print("STOP LOSS RESPONSE: {r}".format(r=sl_resp))

    # If BingX complains about SL being on the wrong side of current price,
    # auto-widen it once and retry with a looser level.
    if sl_resp.get("code") != 0:
        msg = (sl_resp.get("msg") or "").lower()
        if (
            "should be greater than the current price" in msg
            or "should be less than the current price" in msg
        ):
            widen_factor = 2.0  # widen by 2x the configured sl_percent
            if direction == "LONG":
                new_sl = entry * (1.0 - (sl_percent * widen_factor) / 100.0)
                if new_sl < sl_price:
                    sl_price = new_sl
            else:  # SHORT
                new_sl = entry * (1.0 + (sl_percent * widen_factor) / 100.0)
                if new_sl > sl_price:
                    sl_price = new_sl

            retry_payload = {
                "symbol": symbol,
                "side": opposite,
                "positionSide": "BOTH",
                "type": "STOP_MARKET",
                "quantity": eff_qty_str,
                "stopPrice": str(sl_price),
                "workingType": "MARK_PRICE",
            }
            print("[SL RETRY] Widening SL and retrying with: {p}".format(
                p=retry_payload
            ))

            sl_resp_retry = await bingx_api_request(
                "POST",
                "/openApi/swap/v2/trade/order",
                client["api_key"],
                client["secret_key"],
                params=retry_payload,
            )
            print("[SL RETRY] RESPONSE: {r}".format(r=sl_resp_retry))

    print(
        "REAL TRADE EXECUTED: {sym} {dir} {lev}x – ${amt:.2f} (order_type={ot})".format(
            sym=symbol,
            dir=direction,
            lev=leverage,
            amt=usdt_amount,
            ot=order_type,
        )
    )
