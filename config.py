# config.py – SINGLE SOURCE OF TRADING CONFIG

"""
All bot configuration lives here.
bot_config.json is NO LONGER USED – edit this file instead.

The BingX *public* API key is stored here so that at runtime you only
need to input the *secret* key.
"""

DEFAULT_CONFIG = {
    # --- Position sizing ---
    # Absolute USDT per trade in normal mode
    "usdt_per_trade": 5.0,

    # --- Risk / limits ---
    "max_open_positions": 14,
    "max_trades_per_day": 20,
    "check_interval_seconds": 8,

    # --- Margin / mode (for future use / info only) ---
    "position_mode": "Isolated",   # informational; actual mode set on BingX UI
    "order_type": "LIMIT",         # 'LIMIT' or 'MARKET' entry

    # --- Take-profit split (4 levels) ---
    "tp1_close_percent": 35.0,
    "tp2_close_percent": 30.0,
    "tp3_close_percent": 20.0,
    "tp4_close_percent": 15.0,

    # --- Trailing stop behaviour ---
    # trailing_activate_after_tp: 1–4, which TP index activates trailing
    "trailing_activate_after_tp": 2,
    # trailing_callback_rate: percentage 0.1–5.0 as BingX expects (e.g. 1.3 means 1.3%)
    "trailing_callback_rate": 1.3,

    # --- Stop-loss clamp (not used to compute SL from entry yet, but kept for safety logic) ---
    "stop_loss_percent": 1.8,

    # --- Leverage limits ---
    # Hard ceiling; the bot will clamp signal leverage to this value.
    "max_allowed_leverage": 50,

    # --- Run mode ---
    # If True, execute_trade will skip all real orders even if main asks for LIVE.
    "dry_run_mode": False,

    # --- BingX API key (PUBLIC KEY) ---
    # This is your BingX API key (NOT the secret). It is safe to store here.
    # At runtime, you will only be prompted for the secret key.
    "bingx_api_key": "AAi5glITD5852TpJ7H3kceVqpUo6o2iJ5Wo9mQcIfDxoBHWuVDT7RtlT7DNKVhaEKBkLCUFCS6fByX3HZOw",
}


def get_config():
    """
    Return a *copy* of the default configuration so callers
    can mutate it without affecting the module-level defaults.
    """
    return DEFAULT_CONFIG.copy()


def prompt_config():
    """
    Very light interactive configurator used by main.py when the user chooses
    'configure' instead of 'load'. It starts from DEFAULT_CONFIG and lets the
    user override a few key fields.
    """
    cfg = get_config()
    print("\nInteractive config – press Enter to keep defaults.")

    def ask_float(key, prompt_text):
        cur = cfg[key]
        s = input(f"{prompt_text} [{cur}]: ").strip()
        if s:
            try:
                cfg[key] = float(s)
            except ValueError:
                print(f"Invalid number for {key}, keeping {cur}")

    def ask_int(key, prompt_text):
        cur = cfg[key]
        s = input(f"{prompt_text} [{cur}]: ").strip()
        if s:
            try:
                cfg[key] = int(s)
            except ValueError:
                print(f"Invalid integer for {key}, keeping {cur}")

    def ask_str(key, prompt_text, allowed=None):
        cur = cfg[key]
        s = input(f"{prompt_text} [{cur}]: ").strip()
        if s:
            if allowed and s not in allowed:
                print(f"Invalid value for {key}, keeping {cur}")
            else:
                cfg[key] = s

    ask_float("usdt_per_trade", "USDT per trade")
    ask_int("max_trades_per_day", "Max trades per day")
    ask_int("check_interval_seconds", "Check interval (seconds)")
    ask_int("max_allowed_leverage", "Max allowed leverage (x)")
    ask_str("order_type", "Order type (LIMIT/MARKET)", allowed=["LIMIT", "MARKET"])

    dry_run_answer = input(f"Dry run mode? (y/n) [{'y' if cfg['dry_run_mode'] else 'n'}]: ").strip().lower()
    if dry_run_answer in ["y", "yes"]:
        cfg["dry_run_mode"] = True
    elif dry_run_answer in ["n", "no"]:
        cfg["dry_run_mode"] = False

    return cfg
