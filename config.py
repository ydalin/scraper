# config.py – FINAL
DEFAULT_CONFIG = {
    # "usdt_per_trade_percent": 5.8, #original
    "usdt_per_trade_percent": .0008, #for testing
    "max_open_positions": 14,
    "max_trades_per_day": 20,
    "check_interval_seconds": 8,
    "position_mode": "Isolated",
    "order_type": "LIMIT",
    "tp1_close_percent": 35.0,
    "tp2_close_percent": 30.0,
    "tp3_close_percent": 20.0,
    "tp4_close_percent": 15.0,
    "trailing_activate_after_tp": 2,
    "trailing_callback_rate": 1.3,
    "stop_loss_percent": 1.8,
    "dry_run_mode": False
}

CONFIG_FILE = "bot_config.json"

def load_config():
    import json, os
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                raw = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(raw)
            return cfg
        except:
            pass
    return DEFAULT_CONFIG.copy()

def get_config():
    return load_config()