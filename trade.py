# trade.py – SYMBOL MAPPING + HYBRID LIMIT FILL + TP/SL/TRAILING

import asyncio
import time
from api import bingx_api_request


# -------------------------------------------------------------------
# Symbol mapping & normalization
# -------------------------------------------------------------------

# Explicit symbol overrides if exchange naming differs from signal.
SYMBOL_MAP = {
    "PIUSDT": "PI-USDT",
    "PI/USDT": "PI-USDT",
    # Add more overrides here if needed:
    # "1000PEPE/USDT": "KPEPE-USDT",
}


def map_symbol(signal_symbol):
    """
    Normalize a signal symbol to BingX swap format.

    Examples:
      'BTC/USDT'  -> 'BTC-USDT'
      'BTCUSDT'   -> 'BTC-USDT'
      ' pi /usdt' -> 'PI-USDT' (via generic logic or SYMBOL_MAP)
    """
    if not signal_symbol:
        return ""

    s = str(signal_symbol).upper().replace(" ", "")

    # First, explicit overrides
    if s in SYMBOL_MAP:
        return SYMBOL_MAP[s]

    # Case 1: 'BTC/USDT'
    if "/" in s:
        base, quote = s.split("/", 1)
        return "%s-%s" % (base, quote)

    # Case 2: 'BTCUSDT'
    if s.endswith("USDT"):
        base = s[:-4]
        return "%s-USDT" % base

    # Fallback: return as-is
    return s


def _normalize_symbol(sym):
    """Normalize symbol for comparison (strip '-', '/', spaces)."""
    if not sym:
        return ""
    return str(sym).replace("-", "").replace("/", "").replace(" ", "").upper()


def format_qty(qty):
    """Format quantity with up to 6 decimals, strip trailing zeros."""
    return ("%.6f" % qty).rstrip("0").rstrip(".")


# -------------------------------------------------------------------
# Position & order status helpers
# -------------------------------------------------------------------

async def _get_position_size(client, symbol):
    """
    Query current position size for a symbol.
    Returns absolute size (>=0), or 0.0 if none.

    Uses normalized symbol matching to handle PIXEL-USDT vs PIXELUSDT.
    """
    symbol = symbol.upper()
    norm_symbol = _normalize_symbol(symbol)

    try:
        resp = await bingx_api_request(
            "GET",
            "/openApi/swap/v2/trade/position",
            client["api_key"],
            client["secret_key"],
            params={"symbol": symbol},
        )
    except Exception as e:
        print("[POS] Error fetching position for %s: %s" % (symbol, e))
        return 0.0

    if resp.get("code") != 0:
        return 0.0

    data = resp.get("data") or []
    if isinstance(data, dict):
        positions = [data]
    else:
        positions = data

    for pos in positions:
        pos_sym = str(pos.get("symbol", "")).upper()
        if _normalize_symbol(pos_sym) != norm_symbol:
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


async def _get_order_status(client, symbol, order_id):
    """
    Query order status for a specific order.
    Returns status string (e.g. 'NEW', 'FILLED', 'PARTIALLY_FILLED', etc.) or '' on error.
    """
    symbol = symbol.upper()
    if not order_id:
        return ""

    try:
        resp = await bingx_api_request(
            "GET",
            "/openApi/swap/v2/trade/order",
            client["api_key"],
            client["secret_key"],
            params={"symbol": symbol, "orderId": str(order_id)},
        )
    except Exception as e:
        print("[ORDER] Error fetching order status for %s %s: %s" % (symbol, order_id, e))
        return ""

    if resp.get("code") != 0:
        return ""

    data = resp.get("data") or {}
    if isinstance(data, list) and data:
        data = data[0]

    status = str(data.get("status", "")).upper()
    return status


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
        "[WAIT] Hybrid fill check for %s: threshold=%.1f%% of %.6f, timeout=%ds"
        % (symbol, threshold * 100.0, intended_qty, timeout)
    )

    while time.time() - start < timeout:
        # Check order status
        status = await _get_order_status(client, symbol, order_id)
        if status:
            print("[WAIT] Order %s status: %s" % (order_id, status))

        # Check position size
        size = await _get_position_size(client, symbol)
        last_size = size
        if size > 0:
            print("[WAIT] Current position size for %s: %.6f" % (symbol, size))

        target = intended_qty * threshold

        # If position big enough, accept
        if size >= target and size > 0:
            print(
                "[WAIT] Position >= threshold: size=%.6f, needed>=%.6f"
                % (size, target)
            )
            return size

        # If order is FILLED and we see any position, accept
        if status == "FILLED" and size > 0:
            print(
                "[WAIT] Order FILLED and position present: size=%.6f, intended=%.6f"
                % (size, intended_qty)
            )
            return size

        await asyncio.sleep(poll_interval)

    print(
        "[WAIT] Hybrid fill timeout for %s. Last position size=%.6f"
        % (symbol, last_size)
    )
    return last_size


async def _cancel_order(client, symbol, order_id, side, order_type, position_side="BOTH"):
    """
    Cancel open orders for a given symbol.

    BingX Perpetual Futures v2 does not expose a simple
    "cancel single order" endpoint, but it *does* provide
    /openApi/swap/v2/trade/allOpenOrders to cancel all open
    orders for a symbol.

    For our use-case ("limit entry didn’t fill, clean it up"),
    it's perfectly fine (and safer) to cancel all open orders
    on that symbol.

    NOTE: order_id, side, order_type, position_side are kept
    in the signature for compatibility with existing calls,
    but are not used.
    """
    sym = symbol.upper()
    payload = {
        "symbol": sym,
    }

    print("[CANCEL] Canceling ALL open orders for %s with payload: %s" % (sym, payload))

    resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/allOpenOrders",
        client["api_key"],
        client["secret_key"],
        params=payload,
    )

    print("[CANCEL] RESPONSE: %s" % resp)
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
        "positionSide": "BOTH",
        "type": "MARKET",
        "quantity": qty_str,
        "workingType": "MARK_PRICE",
    }
    print("[CLOSE] Closing partial position at MARKET: %s" % payload)
    resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        params=payload,
    )
    print("[CLOSE] RESPONSE: %s" % resp)
    return resp


# -------------------------------------------------------------------
# Main trade execution
# -------------------------------------------------------------------

async def execute_trade(client, signal, usdt_amount, leverage=10, config=None, dry_run=False):
    """
    Execute a trade based on a Telegram signal.

    - Uses MARKET or LIMIT based on config["order_type"].
    - LIMIT:
        * place limit entry
        * hybrid wait (order status + position size) up to timeout
        * if not filled enough: cancel order, close any partial at market, stop.
        * if filled enough: place TP/SL/trailing normally.
    - MARKET:
        * place entry and then TP/SL/trailing immediately (no waiting).
    """
    if config is None:
        from config import get_config
        config = get_config()

    # Symbol mapping from signal to BingX futures format
    raw_symbol = signal.get("symbol", "")
    symbol = map_symbol(raw_symbol)

    direction = str(signal.get("direction", "")).upper()  # LONG / SHORT
    entry = float(signal.get("entry", 0.0))
    targets = [float(t) for t in signal.get("targets", [])[:4]]
    stoploss = float(signal.get("stoploss", 0.0))

    # Basic sanity checks
    if not symbol or entry <= 0 or not direction or not targets or stoploss <= 0:
        print(
            "[ERROR] Invalid signal in execute_trade: "
            "raw_symbol=%r, mapped_symbol=%r, direction=%r, entry=%r, targets=%r, stoploss=%r"
            % (raw_symbol, symbol, direction, entry, targets, stoploss)
        )
        return

    # Position size from USDT, leverage, entry
    qty = (usdt_amount * leverage) / entry
    qty_str = format_qty(qty)

    side = "BUY" if direction == "LONG" else "SELL"
    opposite = "SELL" if direction == "LONG" else "BUY"

    # ENTRY ORDER TYPE from config
    order_type = str(config.get("order_type", "MARKET")).upper()
    if order_type not in ("MARKET", "LIMIT"):
        order_type = "MARKET"

    # LIMIT fill behavior (defaults if not in config)
    fill_threshold = float(config.get("limit_fill_threshold", 0.01))         # 1% default
    fill_timeout = int(config.get("limit_fill_timeout_seconds", 180))        # 180s default

    print("======================================================================")
    print("EXECUTING TRADE for %s" % symbol)
    print("  Direction:   %s" % direction)
    print("  Order type:  %s" % order_type)
    print("  Entry:       %s" % entry)
    print("  Qty (intended): %s (≈ %.4f USDT at %dx)" % (qty_str, usdt_amount, leverage))
    print("  Targets:     %s" % targets)
    print("  Stoploss:    %s" % stoploss)
    print("======================================================================")

    # ---------- ENTRY ORDER ----------
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

    print("ENTRY ORDER: %s" % entry_payload)

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
    print("ENTRY RESPONSE: %s" % entry_resp)

    if entry_resp.get("code") != 0:
        print("[ENTRY ERROR] %s" % entry_resp.get("msg"))
        return

    # Extract orderId (used for status & cancel)
    order_data = (entry_resp.get("data") or {}).get("order") or {}
    entry_order_id = order_data.get("orderId") or order_data.get("orderID")

    # Decide effective quantity:
    effective_qty = qty

    if order_type == "LIMIT":
        # Hybrid wait for fill
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
                "[INFO] LIMIT entry sufficiently filled: %.6f (>= %.6f)"
                % (filled_size, target_size)
            )
        else:
            # Not filled enough within timeout: cancel order, close partial (if any), and stop
            print(
                "[INFO] LIMIT entry NOT filled enough within timeout. "
                "filled_size=%.6f, needed>=%.6f"
                % (filled_size, target_size)
            )
            if entry_order_id is not None:
                await _cancel_order(client, symbol, entry_order_id, side, order_type, "BOTH")

            if filled_size > 0:
                # Close any partial position at market for safety
                await _close_position_market(client, symbol, direction, filled_size)

            print("[INFO] Exiting without placing TP/SL/trailing.")
            return

    else:
        # MARKET entry: if API returned executedQty, we can use that as effective_qty
        executed = order_data.get("executedQty")
        try:
            if executed is not None:
                executed_f = float(executed)
                if executed_f > 0:
                    effective_qty = executed_f
        except Exception:
            pass

    eff_qty_str = format_qty(effective_qty)
    print("[INFO] Using effective_qty=%s for exits." % eff_qty_str)

    # ---------- TAKE PROFITS ----------
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

        print("TP%d ORDER: %s" % (i, tp_payload))

        tp_resp = await bingx_api_request(
            "POST",
            "/openApi/swap/v2/trade/order",
            client["api_key"],
            client["secret_key"],
            params=tp_payload,
        )
        print("TP%d RESPONSE: %s" % (i, tp_resp))

    # ---------- TRAILING STOP ----------
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

            print("TRAILING STOP ORDER: %s" % trail_payload)

            trail_resp = await bingx_api_request(
                "POST",
                "/openApi/swap/v2/trade/order",
                client["api_key"],
                client["secret_key"],
                params=trail_payload,
            )
            print("TRAILING STOP RESPONSE: %s" % trail_resp)
        else:
            print("[TRAILING] No remaining quantity for trailing stop.")
    else:
        print("[TRAILING] Trailing stop disabled or invalid config.")

    # ---------- STOP LOSS ----------
    sl_payload = {
        "symbol": symbol,
        "side": opposite,
        "positionSide": "BOTH",
        "type": "STOP_MARKET",
        "quantity": eff_qty_str,
        "stopPrice": str(stoploss),
        "workingType": "MARK_PRICE",
    }

    print("STOP LOSS ORDER: %s" % sl_payload)

    sl_resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        params=sl_payload,
    )
    print("STOP LOSS RESPONSE: %s" % sl_resp)

    print(
        "REAL TRADE EXECUTED: %s %s %dx – $%.2f (order_type=%s)"
        % (symbol, direction, leverage, usdt_amount, order_type)
    )
