# config.py – FINAL SETTINGS
DEFAULT_CONFIG = {
    "usdt_per_trade_percent": 5.8,          # 5.8% of balance (~$348 on $6k)
    "max_open_positions": 14,               # Safety limit
    "max_trades_per_day": 20,
    "check_interval_seconds": 8,
    "position_mode": "Isolated",
    "order_type": "LIMIT",

    "tp1_close_percent": 35.0,
    "tp2_close_percent": 30.0,
    "tp3_close_percent": 20.0,
    "tp4_close_percent": 15.0,

    # NEW: how trailing stop behaves
    # "none"      -> no trailing stop
    # "from_tp"   -> activate trailing from one of the TPs (see trailing_activate_after_tp)
    # "from_entry"-> activate trailing from the entry price
    "trailing_stop_mode": "from_tp",

    # For "from_tp" mode: which TP index (1-4) starts the trailing
    "trailing_activate_after_tp": 2,

    # BingX trailing priceRate, e.g. 1.3 = 1.3%
    "trailing_callback_rate": 1.3,

    # Not used right now (you’re using SL from the signal),
    # but kept for future logic if you want to compute SL from entry.
    "stop_loss_percent": 1.8,

    # If True, execute_trade will be dry-run even if called with dry_run=False
    "dry_run_mode": False
}

CONFIG_FILE = "bot_config.json"

def load_config():
    import json, os
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(config)
                return merged
        except:
            pass
    return DEFAULT_CONFIG.copy()

def get_config():
    return load_config()
