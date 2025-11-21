# config.py – CONFIG + LEGACY MIGRATION (NO BINGX SYNTAX CHANGES)

CONFIG_FILE = "bot_config.json"

# Core default config based on your desired spec
DEFAULT_CONFIG = {
    # --- Position sizing ---
    # Percent of current balance per trade (normal mode)
    "usdt_per_trade_percent": 5.8,          # ~348 USDT on 6k

    # If you ever want absolute sizing instead of percent:
    "use_absolute_usdt": False,
    "absolute_usdt_per_trade": 5.0,         # only used if use_absolute_usdt=True

    # --- Risk / limits ---
    "max_open_positions": 14,               # hard safety cap
    "max_trades_per_day": 20,               # per-run/day cap
    "max_leverage": 10,                     # never exceed this in normal mode

    # --- Loop / timing ---
    "check_interval_seconds": 8,

    # --- Order / margin settings (informational; logic mainly in trade.py) ---
    "position_mode": "One-Way",             # account mode (your account must match)
    "margin_mode": "ISOLATED",              # isolated margin
    "order_type": "LIMIT",

    # --- Take profit split (4 levels) ---
    "tp1_close_percent": 35.0,
    "tp2_close_percent": 30.0,
    "tp3_close_percent": 20.0,
    "tp4_close_percent": 15.0,

    # --- Trailing stop ---
    # Activate trailing after which TP index (1-4)
    "trailing_activate_after_tp": 2,
    # Trailing callback rate in percent (1.3% => 0.013 in BingX payload)
    "trailing_callback_rate": 1.3,

    # --- Stop-loss clamp ---
    # Max allowed distance from entry in percent.
    # We clamp in main.py: use signal SL if tighter, else limit to this.
    "stop_loss_percent": 1.8,

    # --- Global dry-run switch ---
    # If True, main.py always calls execute_trade(..., dry_run=True)
    "dry_run_mode": False,
}


def _migrate_legacy_config(raw: dict) -> dict:
    """
    Take keys from bot_config.json and map them into the new schema.

    We DO NOT change any BingX API syntax here – this is purely configuration.
    """
    cfg = DEFAULT_CONFIG.copy()

    # Legacy absolute usdt per trade
    if "usdt_per_trade" in raw:
        try:
            cfg["absolute_usdt_per_trade"] = float(raw["usdt_per_trade"])
            # If user explicitly configured this, we can respect it:
            # but main.py still uses percent by default unless you flip use_absolute_usdt.
        except Exception:
            pass

    # Max trades per day
    if "max_trades_per_day" in raw:
        try:
            cfg["max_trades_per_day"] = max(1, int(raw["max_trades_per_day"]))
        except Exception:
            pass

    # Check interval
    if "check_interval_seconds" in raw:
        try:
            cfg["check_interval_seconds"] = max(1, int(raw["check_interval_seconds"]))
        except Exception:
            pass

    # Position / order type (informational)
    if "position_mode" in raw:
        cfg["position_mode"] = str(raw["position_mode"])
    if "order_type" in raw:
        cfg["order_type"] = str(raw["order_type"])

    # TP split
    for key in ("tp1_close_percent", "tp2_close_percent",
                "tp3_close_percent", "tp4_close_percent"):
        if key in raw:
            try:
                cfg[key] = float(raw[key])
            except Exception:
                pass

    # Trailing activation from legacy "trail_sl_on_tp"
    if "trail_sl_on_tp" in raw:
        try:
            cfg["trailing_activate_after_tp"] = int(raw["trail_sl_on_tp"])
        except Exception:
            pass

    # Legacy leverage cap
    if "max_allowed_leverage" in raw:
        try:
            cfg["max_leverage"] = int(raw["max_allowed_leverage"])
        except Exception:
            pass

    # Legacy dry-run flag
    if "dry_run_mode" in raw:
        cfg["dry_run_mode"] = bool(raw["dry_run_mode"])

    return cfg


def load_config():
    import json, os

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            # If file is broken, fall back to defaults.
            return DEFAULT_CONFIG.copy()

        # Merge & migrate into our default structure
        return _migrate_legacy_config(raw)

    # No config file: just use defaults
    return DEFAULT_CONFIG.copy()


def get_config():
    return load_config()
