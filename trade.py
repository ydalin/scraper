# trade.py – LIMIT/MARKET entry + separate TP/SL/trailing, symbol mapping, leverage clamp
# Python 3.8 compatible

import asyncio

from api import bingx_api_request
from config import get_config


# ---------------------------------------------------------------------------
# Symbol mapping / normalization
# ---------------------------------------------------------------------------

SYMBOL_MAP = {
    # Explicit overrides if needed
    "PIUSDT": "PI-USDT",
    "PI/USDT": "PI-USDT",
}


def _normalize_symbol_text(sym):
    if not sym:
        return ""
    return str(sym).upper().replace(" ", "")


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

    s = _normalize_symbol_text(signal_symbol)

    # First, explicit overrides
    if s in SYMBOL_MAP:
        return SYMBOL_MAP[s]

    # 'BTC/USDT' -> 'BTC-USDT'
    if "/" in s:
        base, quote = s.split("/", 1)
        return "%s-%s" % (base, quote)

    # 'BTCUSDT' -> 'BTC-USDT'
    if s.endswith("USDT"):
        base = s[:-4]
        return "%s-USDT" % base

    # Fallback: return as-is
    return s


def format_qty(qty):
    """Format quantity with up to 6 decimals, strip trailing zeros."""
    return ("%.6f" % qty).rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Helpers: leverage + fill polling
# ---------------------------------------------------------------------------

async def set_symbol_leverage(client, symbol, leverage, dry_run=False):
    """
    Set opening leverage for a symbol via BingX API.

    Endpoint: /openApi/swap/v2/trade/leverage
    Method:   POST
    Params:
      - symbol: e.g. 'BTC-USDT'
      - side:   'BOTH' in One-Way mode
      - leverage: integer (as string is fine)

    This is always called before placing the entry order so the exchange
    leverage matches what the bot uses for position sizing.
    """
    # Safety clamp: leverage must be at least 1
    try:
        lev_int = int(leverage)
    except Exception:
        lev_int = 1
    if lev_int < 1:
        lev_int = 1

    if dry_run:
        print("[LEVERAGE] (dry run) would set leverage for %s to %sx" % (symbol, lev_int))
        return

    payload = {
        "symbol": symbol,
        "side": "BOTH",          # One-Way mode
        "leverage": str(lev_int),
        "recvWindow": 5000,
    }

    print("[LEVERAGE] Setting leverage for %s to %sx with payload: %s"
          % (symbol, lev_int, payload))

    resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/leverage",
        client["api_key"],
        client["secret_key"],
        params=payload,
    )

    print("[LEVERAGE] RESPONSE:", resp)


async def wait_for_position_open(client, symbol, timeout_seconds=300, poll_interval=3.0):
    """
    Poll /openApi/swap/v2/user/positions until we see a position for `symbol`
    (or until timeout).

    We do NOT try to measure percentage fill; we simply wait until BingX
    reports any position for that symbol. This is enough to avoid
    'position not exist' errors when placing TP/SL/trailing.

    Returns True if position found, False if timed out or on repeated errors.
    """
    start = asyncio.get_event_loop().time()
    api_key = client["api_key"]
    secret_key = client["secret_key"]

    print("[WAIT] Waiting for position to appear for %s (timeout %ss)" % (symbol, timeout_seconds))

    while True:
        elapsed = asyncio.get_event_loop().time() - start
        if elapsed > timeout_seconds:
            print("[WAIT] Timeout waiting for position on %s." % symbol)
            return False

        try:
            resp = await bingx_api_request(
                "GET",
                "/openApi/swap/v2/user/positions",
                api_key,
                secret_key,
            )
            if resp.get("code") == 0:
                data = resp.get("data") or []
                if isinstance(data, list):
                    for pos in data:
                        try:
                            pos_sym = pos.get("symbol")
                        except AttributeError:
                            continue
                        if pos_sym == symbol:
                            print("[WAIT] Position for %s detected in /user/positions." % symbol)
                            return True
            else:
                print("[WAIT] positions error for %s: %s" % (symbol, resp.get("msg")))
        except Exception as e:
            print("[WAIT] Exception while polling positions for %s: %s" % (symbol, e))

        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Main trade execution
# ---------------------------------------------------------------------------

async def execute_trade(
    client,
    signal,
    usdt_amount,
    leverage=10,
    config=None,
    dry_run=False,
):
    """
    Execute a trade on BingX based on a parsed Telegram signal.

    - LIMIT (or MARKET) entry
    - Multi-TP exits as separate TAKE_PROFIT_MARKET orders
    - Separate STOP_MARKET stop-loss
    - Optional TRAILING_STOP_MARKET on the remaining quantity
    - Fill-poll block – we wait for a position to exist before
      placing TP/SL/trailing to avoid 'position not exist' errors.
    """
    if config is None:
        config = get_config()

    raw_symbol = signal.get("symbol", "")
    symbol = map_symbol(raw_symbol)
    direction = str(signal.get("direction", "")).upper()  # LONG / SHORT
    entry = float(signal.get("entry", 0.0))
    targets_raw = signal.get("targets", [])
    targets = [float(t) for t in targets_raw[:4]]
    stoploss = float(signal.get("stoploss", 0.0))

    # Basic sanity checks
    if not symbol or entry <= 0 or not direction or not targets or stoploss <= 0:
        print(
            "[ERROR] Invalid signal in execute_trade: "
            "raw_symbol=%r mapped_symbol=%r direction=%r entry=%r targets=%r stoploss=%r"
            % (raw_symbol, symbol, direction, entry, targets, stoploss)
        )
        return

    # -----------------------------------------------------------------------
    # Leverage: clamp by signal, by argument, and by config cap
    # -----------------------------------------------------------------------
    signal_lev = signal.get("leverage")
    try:
        if signal_lev is None:
            signal_lev = leverage or 1
        else:
            signal_lev = int(signal_lev)
    except Exception:
        signal_lev = leverage or 1 or 1

    max_lev_cfg = config.get("max_allowed_leverage", 10)
    try:
        max_lev_cfg = int(max_lev_cfg)
    except Exception:
        max_lev_cfg = 10
    if max_lev_cfg < 1:
        max_lev_cfg = 1

    lev_candidates = []
    for cand in (signal_lev, leverage, max_lev_cfg):
        try:
            c = int(cand)
            if c > 0:
                lev_candidates.append(c)
        except Exception:
            pass

    if lev_candidates:
        eff_leverage = max(1, min(lev_candidates))
    else:
        eff_leverage = 1

    # -----------------------------------------------------------------------
    # Position size from USDT, leverage, entry
    # -----------------------------------------------------------------------
    qty = (usdt_amount * eff_leverage) / entry
    qty_str = format_qty(qty)

    side = "BUY" if direction == "LONG" else "SELL"
    close_side = "SELL" if direction == "LONG" else "BUY"

    # ENTRY ORDER TYPE from config
    order_type = str(config.get("order_type", "LIMIT")).upper()
    if order_type not in ("MARKET", "LIMIT"):
        order_type = "LIMIT"

    print("======================================================================")
    print("EXECUTING TRADE for %s" % symbol)
    print("  Direction:   %s" % direction)
    print("  Order type:  %s" % order_type)
    print("  Entry:       %s" % entry)
    print("  Qty (intended): %s (≈ %.4f USDT at %dx)" % (qty_str, usdt_amount, eff_leverage))
    print("  Targets:     %s" % targets)
    print("  Stoploss:    %s" % stoploss)
    print("======================================================================")

    # -----------------------------------------------------------------------
    # ALWAYS TRY TO SET LEVERAGE (real API call)
    # -----------------------------------------------------------------------
    await set_symbol_leverage(client, symbol, eff_leverage, dry_run=dry_run)

    # -----------------------------------------------------------------------
    # ENTRY ORDER
    # -----------------------------------------------------------------------
    entry_payload = {
        "symbol": symbol,
        "side": side,
        "positionSide": "BOTH",   # One-Way mode
        "type": order_type,
        "quantity": qty_str,
        "workingType": "MARK_PRICE",
        "leverage": str(eff_leverage),
    }
    if order_type == "LIMIT":
        entry_payload["price"] = str(entry)
        entry_payload["timeInForce"] = "GTC"

    print("ENTRY ORDER:", entry_payload)

    # Honor global/config dry run
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
    print("ENTRY RESPONSE:", entry_resp)

    if entry_resp.get("code") != 0:
        print("[ENTRY ERROR]", entry_resp.get("msg"))
        return

    # -----------------------------------------------------------------------
    # FILL POLLING: wait until BingX reports a position for this symbol
    # -----------------------------------------------------------------------
    filled = await wait_for_position_open(
        client,
        symbol,
        timeout_seconds=300,      # adjust if you want longer
        poll_interval=3.0,
    )
    if not filled:
        print("[INFO] Position for %s never appeared. Skipping TP/SL/trailing." % symbol)
        return

    # We will base TP/SL quantities on intended qty (simple).
    effective_qty = qty
    eff_qty_str = format_qty(effective_qty)
    print("[INFO] Using effective_qty=%s for exits." % eff_qty_str)

    # -----------------------------------------------------------------------
    # TAKE PROFITS (separate TAKE_PROFIT_MARKET orders)
    # -----------------------------------------------------------------------
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
            "side": close_side,
            "positionSide": "BOTH",
            "type": "TAKE_PROFIT_MARKET",
            "quantity": tp_qty_str,
            "stopPrice": str(tp_price),
            "workingType": "MARK_PRICE",
        }

        print("TP%d ORDER:" % i, tp_payload)

        tp_resp = await bingx_api_request(
            "POST",
            "/openApi/swap/v2/trade/order",
            client["api_key"],
            client["secret_key"],
            params=tp_payload,
        )
        print("TP%d RESPONSE:" % i, tp_resp)

    # -----------------------------------------------------------------------
    # TRAILING STOP MARKET on remaining size (optional)
    # -----------------------------------------------------------------------
    trail_tp_idx = int(config.get("trailing_activate_after_tp", 0))
    callback_rate = float(config.get("trailing_callback_rate", 0.0))

    if 1 <= trail_tp_idx <= len(targets) and callback_rate > 0:
        used_pct = tp1_pct + tp2_pct + tp3_pct + tp4_pct
        remain_pct = max(0.0, 100.0 - used_pct)

        if remain_pct > 0:
            trail_qty = effective_qty * (remain_pct / 100.0)
            trail_qty_str = format_qty(trail_qty)
            activation_price = targets[trail_tp_idx - 1]

            trail_payload = {
                "symbol": symbol,
                "side": close_side,
                "positionSide": "BOTH",
                "type": "TRAILING_STOP_MARKET",
                "quantity": trail_qty_str,
                "activationPrice": str(activation_price),
                # BingX expects callbackRate as percent 0.1–5.0 (not fraction)
                "callbackRate": str(callback_rate),
                "workingType": "MARK_PRICE",
            }

            print("TRAILING STOP ORDER:", trail_payload)

            trail_resp = await bingx_api_request(
                "POST",
                "/openApi/swap/v2/trade/order",
                client["api_key"],
                client["secret_key"],
                params=trail_payload,
            )
            print("TRAILING STOP RESPONSE:", trail_resp)
        else:
            print("[TRAILING] No remaining quantity for trailing stop.")
    else:
        print("[TRAILING] Trailing stop disabled or invalid config.")

    # -----------------------------------------------------------------------
    # STOP LOSS (STOP_MARKET) on full effective quantity
    # -----------------------------------------------------------------------
    sl_payload = {
        "symbol": symbol,
        "side": close_side,
        "positionSide": "BOTH",
        "type": "STOP_MARKET",
        "quantity": eff_qty_str,
        "stopPrice": str(stoploss),
        "workingType": "MARK_PRICE",
    }

    print("STOP LOSS ORDER:", sl_payload)

    sl_resp = await bingx_api_request(
        "POST",
        "/openApi/swap/v2/trade/order",
        client["api_key"],
        client["secret_key"],
        params=sl_payload,
    )
    print("STOP LOSS RESPONSE:", sl_resp)

    print(
        "REAL TRADE EXECUTED: %s %s %dx – $%.2f (order_type=%s)"
        % (symbol, direction, eff_leverage, usdt_amount, order_type)
    )
