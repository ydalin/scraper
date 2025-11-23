# config.py – FINAL WORKING VERSION (November 2025)
import json
import os

CONFIG_FILE = "bot_config.json"

DEFAULT_CONFIG = {
    "usdt_per_trade_percent": 5.8,
    "max_open_positions": 14,
    "max_trades_per_day": 20,
    "check_interval_seconds": 8,
    "position_mode": "One-Way",
    "margin_mode": "ISOLATED",
    "order_type": "LIMIT",  # or "MARKET"
    "tp1_close_percent": 35.0,
    "tp2_close_percent": 30.0,
    "tp3_close_percent": 20.0,
    "tp4_close_percent": 15.0,
    "trailing_activate_after_tp": 2,
    "trailing_callback_rate": 1.3,   # clamped to 0.01–0.1 in code
    "stop_loss_percent": 1.8,
    "dry_run_mode": False,
    "min_24h_volume_usd": 30_000_000,
    "max_funding_rate": 0.05,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(raw)
            return cfg
        except Exception as e:
            print(f"Config load error: {e}. Using defaults.")
    return DEFAULT_CONFIG.copy()

def get_config():
    return load_config()