# config.py – CONFIG + LEGACY MIGRATION (NO BINGX SYNTAX CHANGES)

CONFIG_FILE = "bot_config.json"

# Core default config based on your desired spec
DEFAULT_CONFIG = {
    # --- Position sizing ---
    # Percent of current balance per trade (normal mode)
    "usdt_per_trade_percent": 5.8,          # ~348 USDT on 6k

    # Optional: absolute USDT amount instead of percentage
    "use_absolute_usdt": False,
    "absolute_usdt_per_trade": 5.0,

    # --- Risk / limits ---
    "max_open_positions": 14,
    "max_trades_per_day": 20,
    "max_leverage": 10,

    # --- Loop / timing ---
    "check_interval_seconds": 8,

    # --- Margin settings (account must match this) ---
    "position_mode": "One-Way",      # One-way mode (positionSide=BOTH)
    "margin_mode": "ISOLATED",

    # --- ENTRY ORDER TYPE ---
    # You requested MARKET instead of LIMIT.
    "order_type": "MARKET",          # <<<<<<━━ NEW DEFAULT ENTRY TYPE

    # --- Take profit split ---
    "tp1_close_percent": 35.0,
    "tp2_close_percent": 30.0,
    "tp3_close_percent": 20.0,
    "tp4_close_percent": 15.0,

    # --- Trailing stop ---
    "trailing_activate_after_tp": 2,
    "trailing_callback_rate": 1.3,

    # --- Stop-loss clamp percentage ---
    "stop_loss_percent": 1.8,

    # --- Global dry-run switch ---
    "dry_run_mode": False,
}
