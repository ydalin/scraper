# config.py – ROBUST CONFIG SYSTEM WITH MIGRATION & VALIDATION

DEFAULT_CONFIG = {
    # Position sizing
    "usdt_per_trade_percent": 5.8,          # percent of balance per trade
    "use_absolute_usdt": False,             # if True, ignore percent and use absolute_usdt_per_trade
    "absolute_usdt_per_trade": 5.0,         # used only if use_absolute_usdt=True

    # Risk / limits
    "max_open_positions": 14,               # Safety limit
    "max_trades_per_day": 20,
    "max_leverage": 10,                     # hard cap on leverage in normal mode

    # Loop / mode
    "check_interval_seconds": 8,
    "position_mode": "Isolated",
    "order_type": "LIMIT",

    # Take profits (% of position size)
    "tp1_close_percent": 35.0,
    "tp2_close_percent": 30.0,
    "tp3_close_percent": 20.0,
    "tp4_close_percent": 15.0,

    # Trailing stop behavior
    # "none"      -> no trailing stop
    # "from_tp"   -> activate trailing from one of the TPs (see trailing_activate_after_tp)
    # "from_entry"-> activate trailing from the entry price
    "trailing_stop_mode": "from_tp",

    # For "from_tp" mode: which TP index (1-4) starts the trailing
    "trailing_activate_after_tp": 2,

    # BingX trailing callback %, e.g. 1.3 = 1.3%
    "trailing_callback_rate": 1.3,

    # Not used right now (you’re using SL from the signal),
    # but kept for future logic if you want to compute SL from entry.
    "stop_loss_percent": 1.8,

    # If True, execute_trade will be dry-run even if called with dry_run=False
    "dry_run_mode": False,
}

CONFIG_FILE = "bot_config.json"


def _migrate_config(user_cfg: dict) -> dict:
    """
    Migrate legacy keys from old configs (like your current bot_config.json)
    into the new schema. This does NOT mutate user_cfg; it returns a dict
    of overrides to apply on top of DEFAULT_CONFIG.
    """
    migrated = {}

    # Legacy: `usdt_per_trade` (absolute dollars) -> new sizing scheme
    if "usdt_per_trade" in user_cfg and "usdt_per_trade_percent" not in user_cfg:
        try:
            migrated["use_absolute_usdt"] = True
            migrated["absolute_usdt_per_trade"] = float(user_cfg["usdt_per_trade"])
        except (TypeError, ValueError):
            pass

    # Legacy: `trail_sl_on_tp` -> `trailing_activate_after_tp`
    if "trail_sl_on_tp" in user_cfg and "trailing_activate_after_tp" not in user_cfg:
        try:
            migrated["trailing_activate_after_tp"] = int(user_cfg["trail_sl_on_tp"])
        except (TypeError, ValueError):
            pass

    # Legacy: `max_allowed_leverage` -> `max_leverage`
    if "max_allowed_leverage" in user_cfg and "max_leverage" not in user_cfg:
        try:
            migrated["max_leverage"] = int(user_cfg["max_allowed_leverage"])
        except (TypeError, ValueError):
            pass

    return migrated


def _validate_config(cfg: dict) -> None:
    """
    Light validation & clamping. Mutates cfg in-place.
    """
    # Percent sizing
    try:
        cfg["usdt_per_trade_percent"] = max(0.1, float(cfg.get("usdt_per_trade_percent", 5.8)))
    except (TypeError, ValueError):
        cfg["usdt_per_trade_percent"] = 5.8

    # Absolute sizing
    try:
        cfg["absolute_usdt_per_trade"] = max(1.0, float(cfg.get("absolute_usdt_per_trade", 5.0)))
    except (TypeError, ValueError):
        cfg["absolute_usdt_per_trade"] = 5.0

    # Max leverage
    try:
        cfg["max_leverage"] = max(1, int(cfg.get("max_leverage", 10)))
    except (TypeError, ValueError):
        cfg["max_leverage"] = 10

    # Max open positions
    try:
        cfg["max_open_positions"] = max(1, int(cfg.get("max_open_positions", 10)))
    except (TypeError, ValueError):
        cfg["max_open_positions"] = 10

    # Check interval
    try:
        cfg["check_interval_seconds"] = max(1, int(cfg.get("check_interval_seconds", 8)))
    except (TypeError, ValueError):
        cfg["check_interval_seconds"] = 8

    # Trailing TP index
    try:
        idx = int(cfg.get("trailing_activate_after_tp", 2))
        cfg["trailing_activate_after_tp"] = max(1, min(4, idx))
    except (TypeError, ValueError):
        cfg["trailing_activate_after_tp"] = 2

    # Trailing callback rate (percentage)
    try:
        cfg["trailing_callback_rate"] = max(0.05, float(cfg.get("trailing_callback_rate", 1.3)))
    except (TypeError, ValueError):
        cfg["trailing_callback_rate"] = 1.3

    # TPs sum sanity (don’t strictly enforce 100, just clamp negatives)
    for key in ("tp1_close_percent", "tp2_close_percent", "tp3_close_percent", "tp4_close_percent"):
        try:
            cfg[key] = max(0.0, float(cfg.get(key, 0.0)))
        except (TypeError, ValueError):
            cfg[key] = 0.0

    # dry_run_mode as bool
    cfg["dry_run_mode"] = bool(cfg.get("dry_run_mode", False))

    if cfg["dry_run_mode"]:
        print("*** WARNING: dry_run_mode is ENABLED – no real orders will be sent. ***")


def load_config():
    import json, os

    cfg = DEFAULT_CONFIG.copy()

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                # Migrate old keys like `usdt_per_trade`, `trail_sl_on_tp`, etc.
                migrated = _migrate_config(user_cfg)
                user_cfg.update(migrated)
                cfg.update(user_cfg)
        except Exception as e:
            print(f"Error loading {CONFIG_FILE}: {e}")

    _validate_config(cfg)
    return cfg


def get_config():
    return load_config()
