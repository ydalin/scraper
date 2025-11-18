# config.py – Configuration Parameters for Trading Bot
import json
import os

# === DEFAULT CONFIGURATION ===
DEFAULT_CONFIG = {
    "usdt_per_trade": 500.0,
    "max_trades_per_day": 5,
    "check_interval_seconds": 30,
    "position_mode": "Cross",  # Cross or Isolated
    "order_type": "MARKET",  # MARKET or LIMIT
    "tp1_close_percent": 25.0,
    "tp2_close_percent": 25.0,
    "tp3_close_percent": 25.0,
    "tp4_close_percent": 25.0,
    "dry_run_mode": False,
    "trail_sl_on_tp": 0,  # 0 = disabled, 1-4 = TP level to move SL to breakeven
    "max_allowed_leverage": 25
}

CONFIG_FILE = "bot_config.json"

def load_config():
    """Load configuration from file or return defaults"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                # Merge with defaults to ensure all keys exist
                merged = DEFAULT_CONFIG.copy()
                merged.update(config)
                return merged
        except Exception as e:
            print(f"[CONFIG ERROR] Failed to load config: {e}")
            print("Using default configuration...")
            return DEFAULT_CONFIG.copy()
    else:
        return DEFAULT_CONFIG.copy()

def save_config(config):
    """Save configuration to file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        print(f"Configuration saved to {CONFIG_FILE}")
        return True
    except Exception as e:
        print(f"[CONFIG ERROR] Failed to save config: {e}")
        return False

def prompt_config():
    """Interactive configuration prompt"""
    print("\n" + "="*70)
    print("TRADING BOT CONFIGURATION")
    print("="*70)

    config = load_config()

    print("\nCurrent configuration:")
    for key, value in config.items():
        print(f"  {key}: {value}")

    print("\n" + "-"*70)
    print("Enter new values (press Enter to keep current value):")
    print("-"*70)

    # USDT per trade
    usdt_input = input(f"USDT per trade [{config['usdt_per_trade']}]: ").strip()
    if usdt_input:
        config['usdt_per_trade'] = float(usdt_input)

    # Max trades per day
    max_trades_input = input(f"Max trades per day [{config['max_trades_per_day']}]: ").strip()
    if max_trades_input:
        config['max_trades_per_day'] = int(max_trades_input)

    # Check interval
    interval_input = input(f"Check interval (seconds) [{config['check_interval_seconds']}]: ").strip()
    if interval_input:
        config['check_interval_seconds'] = int(interval_input)

    # Position mode
    position_mode_input = input(f"Position mode (Cross/Isolated) [{config['position_mode']}]: ").strip()
    if position_mode_input:
        config['position_mode'] = position_mode_input.capitalize()

    # Order type
    order_type_input = input(f"Order type (MARKET/LIMIT) [{config['order_type']}]: ").strip()
    if order_type_input:
        config['order_type'] = order_type_input.upper()

    # TP percentages
    print("\nTake Profit Close Percentages:")
    tp1_input = input(f"TP1 close % [{config['tp1_close_percent']}]: ").strip()
    if tp1_input:
        config['tp1_close_percent'] = float(tp1_input)

    tp2_input = input(f"TP2 close % [{config['tp2_close_percent']}]: ").strip()
    if tp2_input:
        config['tp2_close_percent'] = float(tp2_input)

    tp3_input = input(f"TP3 close % [{config['tp3_close_percent']}]: ").strip()
    if tp3_input:
        config['tp3_close_percent'] = float(tp3_input)
    tp4_input = input(f"TP4 close % [{config['tp4_close_percent']}]: ").strip()
    if tp4_input:
        config['tp4_close_percent'] = float(tp4_input)

    # Dry run mode
    dry_run_input = input(f"Dry run mode (True/False) [{config['dry_run_mode']}]: ").strip()
    if dry_run_input:
        config['dry_run_mode'] = dry_run_input.lower() in ['true', '1', 'yes', 'y']

    # Trail SL on TP
    trail_sl_input = input(f"Trail SL to breakeven on TP level (0-4, 0=disabled) [{config['trail_sl_on_tp']}]: ").strip()
    if trail_sl_input:
        config['trail_sl_on_tp'] = int(trail_sl_input)
    # Max allowed leverage
    max_lev_input = input(f"Max allowed leverage [{config['max_allowed_leverage']}]: ").strip()
    if max_lev_input:
        config['max_allowed_leverage'] = int(max_lev_input)

    # Save configuration
    save_choice = input("\nSave configuration to file? (y/n): ").strip().lower()
    if save_choice in ['y', 'yes']:
        save_config(config)

    return config

def get_config():
    """Get configuration (loads from file or prompts user)"""
    return load_config()

