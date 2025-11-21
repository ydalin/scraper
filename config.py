# config.py – FINAL WORKING VERSION (MARKET ENTRY)

import json
import os

CONFIG_FILE = "bot_config.json"

DEFAULT_CONFIG = {
    # --- Position sizing ---
    "usdt_per_trade_percent": 5.8,
    "use_absolute_usdt": False,
    "absolute_usdt_per_trade": 5.0,

    # --- Risk limits ---
    "max_open_positions": 14,
    "max_trades_per_day": 20,
    "max_leverage": 10,

    # --- Loop ---
    "check_interval_seconds": 8,

    # --- Margin / mode ---
    "position_mode": "One-Way",
    "margin_mode": "ISOLATED",

    # --- ENTRY TYPE ---  (you requested MARKET)
    "order_type": "LIMIT",

    # --- TP split ---
    "tp1_close_percent": 35.0,
    "tp2_close_percent": 30.0,
    "tp3_close_percent": 20.0,
    "tp4_close_percent": 15.0,

    # --- Trailing ---
    "trailing_activate_after_tp": 2,
    "trailing_callback_rate": 1.3,

    # --- SL clamp ---
    "stop_loss_percent": 1.8,

    # --- Dry-run ---
    "dry_run_mode": False,
}


def _migrate_legacy_config(raw: dict) -> dict:
    cfg = DEFAULT_CONFIG.copy()

    # Preserve all simple overrides if they exist in the JSON
    for k, v in raw.items():
        if k in cfg:
            cfg[k] = v

    # Allow "max_allowed_leverage" legacy key
    if "max_allowed_leverage" in raw:
        cfg["max_leverage"] = raw["max_allowed_leverage"]

    return cfg


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return _migrate_legacy_config(raw)
        except Exception:
            return DEFAULT_CONFIG.copy()

    return DEFAULT_CONFIG.copy()


def get_config():
    """This is required by main.py — DO NOT REMOVE."""
    return load_config()
