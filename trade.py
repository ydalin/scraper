# trade.py – LIMIT entry + separate TP/SL/trailing, with symbol mapping and leverage clamp
from typing import Optional

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
        return f"{base}-{quote}"

    # 'BTCUSDT' -> 'BTC-USDT'
    if s.endswith("USDT"):
        base = s[:-4]
        return f"{base}-USDT"

    # Fallback: return as-is
    return s


def format_qty(qty: float) -> str:
    """Format quantity with up to 6 decimals, strip trailing zeros."""
    return ("%.6f" % qty).rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Main trade execution
# ---------------------------------------------------------------------------

async def execute_trade(
    client: dict,
    signal: dict,
    usdt_amount: float,
    leverage: int = 10,
    config: Optional[dict] = None,
    dry_run: bool = False,
):
    """
    Execute a trade on BingX based on a parsed Telegram signal.

    - LIMIT (or MARKET) entry
    - Multi-TP exits as separate TAKE_PROFIT_MARKET orders
    - Separate STOP_MARKET stop-loss
    - Optional TRAILING_STOP_MARKET on the remaining quantity
    - No polling or fill-waiting: exits are placed immediately after entry.
    """
    if config is None:
        config = get_config()

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
            f"raw_symbol={raw_symbol!r} mapped_symbol={symbol!r} "
            f"direction={direction!r} entry={entry!r} targets={targets!r} stoploss={stoploss!r}"
        )
        return

    # -----------------------------------------------------------------------
    # Leverage: clamp by both config and the leverage argument
    # -----------------------------------------------------------------------
    # Signal may contain its own leverage; if so we clamp it.
    signal_lev = signal.get("leverage")
    try:
        signal_lev = int(signal_lev) if signal_lev is not None else leverage or 1
    except Exception:
        signal_lev = leverage or 1 or 1

    # Config cap
    max_lev_cfg = config.get("max_allowed_leverage", 10)
    try:
        max_lev_cfg = int(max_lev_cfg)
    except Exception:
        max_lev_cfg = 10
    if max_lev_cfg < 1:
        max_lev_cfg = 1

    # Effective leverage = min( what main.py asked, what signal said, config cap )
    lev_candidates = []
    for cand in (signal_lev, leverage, max_lev_cfg):
        try:
            c = int(cand)
            if c > 0:
                lev_candidates.append(c)
        except Exception:
            continue

    eff_leverage = max(1, min(lev_candidates)) if lev_candidates else 1

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
    print(f"EXECUTING TRADE for {symbol}")
    print(f"  Direction:   {direction}")
    print(f"  Order type:  {order_type}")
    print(f"  Entry:       {entry}")
    print(f"  Qty (intended): {qty_str} (≈ {usdt_amount:.4f} USDT at {eff_leverage}x)")
    print(f"  Targets:     {targets}")
    print(f"  Stoploss:    {stoploss}")
    print("======================================================================")

    # -----------------------------------------------------------------------
    # ENTRY ORDER
    # -----------------------------------------------------------------------
    entry_payload: dict[str, str] = {
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

    # We will base TP/SL quantities on intended qty (simple, no polling).
    effective_qty = qty
    eff_qty_str = format_qty(effective_qty)
    print(f"[INFO] Using effective_qty={eff_qty_str} for exits.")

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

        print(f"TP{i} ORDER:", tp_payload)

        tp_resp = await bingx_api_request(
            "POST",
            "/openApi/swap/v2/trade/order",
            client["api_key"],
            client["secret_key"],
            params=tp_payload,
        )
        print(f"TP{i} RESPONSE:", tp_resp)

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
        f"REAL TRADE EXECUTED: {symbol} {direction} {eff_leverage}x – ${usdt_amount:.2f} (order_type={order_type})"
    )
