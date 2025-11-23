# main.py – BINGX ×10 FUTURES BOT
# - Normal mode: 5.8% of balance, max 10x leverage
# - Tiny test: $1–$9 and max 2x leverage
# - Live Telegram (Telethon) OR file-based (telegram_messages.txt)
# - Stop-loss clamp: max stop_loss_percent away from entry

import asyncio
import hashlib
import getpass
import re

from telethon.tl.types import InputPeerChannel

from trade import execute_trade
from api import bingx_api_request
from bot_telegram import parse_signal, init_telegram, read_credentials
import bot_telegram
from config import get_config


print("\n" + "=" * 70)
print("   BINGX ×10 FUTURES BOT – LIVE MONEY")
print("=" * 70)

api_key = getpass.getpass("   Enter BingX API Key      : ").strip()
secret_key = getpass.getpass("   Enter BingX Secret Key   : ").strip()

# Tiny test vs normal sizing
test = input("   Tiny test mode ($1–$9 + 1–2x) or Normal mode? (t/n) [n]: ").strip().lower() == "t"
print("   → TINY TEST MODE – $1–$9 + 1–2x leverage"
      if test else "   → NORMAL MODE – 5.8% + config leverage cap")

use_live = False
if not test:
    # Only ask for live Telegram in normal mode
    live_choice = input("   Use LIVE Telegram scraping or local file? (live/file) [file]: ").strip().lower()
    use_live = (live_choice == "live")

print("=" * 70 + "\n")

client_bingx = {
    "api_key": api_key,
    "secret_key": secret_key,
    "base_url": "https://open-api.bingx.com",
}

config = get_config()

if config.get("dry_run_mode", False):
    print("⚠ DRY-RUN MODE ENABLED IN CONFIG – no real orders will be sent.\n")

print(
    f"[CONFIG] usdt_per_trade_percent={config['usdt_per_trade_percent']}%, "
    f"max_open_positions={config['max_open_positions']}, "
    f"max_trades_per_day={config['max_trades_per_day']}, "
    f"max_leverage={config['max_leverage']}, "
    f"stop_loss_percent={config['stop_loss_percent']}%, "
    f"trailing_activate_after_tp={config['trailing_activate_after_tp']}, "
    f"trailing_callback_rate={config['trailing_callback_rate']}%"
)


# ------------------------------------------------
# Helpers: BingX
# ------------------------------------------------

async def get_balance() -> float:
    """
    Fetch futures balance from BingX.

    We reuse the same endpoint pattern you've been using:
    /openApi/swap/v2/user/balance
    """
    try:
        resp = await bingx_api_request(
            "GET",
            "/openApi/swap/v2/user/balance",
            client_bingx["api_key"],
            client_bingx["secret_key"],
        )
    except Exception as e:
        print(f"[BALANCE ERROR] {e}")
        return 6000.0

    if resp.get("code") != 0:
        return 6000.0

    data = resp.get("data") or {}
    # Handle list or dict shapes
    if isinstance(data, list) and data:
        bal_info = data[0].get("balance", data[0])
    elif isinstance(data, dict):
        bal_info = data.get("balance", data)
    else:
        return 6000.0

    for key in ("availableMargin", "availableBalance", "equity", "balance"):
        val = bal_info.get(key)
        if val is not None:
            try:
                return float(val)
            except Exception:
                continue

    return 6000.0


async def get_open_positions_count() -> int:
    """
    Count open futures positions.

    Reuses the trade/position-style endpoint you've been using.
    """
    try:
        resp = await bingx_api_request(
            "GET",
            "/openApi/swap/v2/trade/position",
            client_bingx["api_key"],
            client_bingx["secret_key"],
        )
    except Exception as e:
        print(f"[POSITION ERROR] {e}")
        return 0

    if resp.get("code") != 0:
        return 0

    data = resp.get("data") or []
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict) and data:
        return 1
    return 0


# ------------------------------------------------
# Helpers: Telegram
# ------------------------------------------------

async def fetch_live_signals(limit=10, n_signals=1, last_message_id=None):
    """Fetch latest PREMIUM SIGNALS from Telegram channel.

    Behaviour:
      - On first call (last_message_id is None): we *prime* last_message_id to the newest
        message ID and return NO signals. This avoids trading on old backlog.
      - On subsequent calls: only messages with msg.id > last_message_id are considered new.
    """
    try:
        # Check if Telegram client is initialized
        if bot_telegram.client is None:
            print("[FETCH ERROR] Telegram client not initialized. Please restart the bot.")
            return [], last_message_id

        # Check if client is connected
        if not bot_telegram.client.is_connected():
            print("[FETCH ERROR] Telegram client not connected. Attempting to reconnect...")
            try:
                await bot_telegram.client.connect()
            except Exception as e:
                print(f"[FETCH ERROR] Failed to reconnect: {e}")
                return [], last_message_id

        # Load channel details
        with open('channel_details.txt') as f:
            lines = f.readlines()
            channel_id = int(lines[0].split(':')[1].strip())
            access_hash = int(lines[1].split(':')[1].strip())

        entity = InputPeerChannel(channel_id, access_hash)
        messages = await bot_telegram.client.get_messages(entity, limit=limit)

        # --- FIRST RUN: prime last_message_id and ignore old signals ---
        if last_message_id is None:
            if messages:
                newest_id = max(m.id for m in messages if m is not None)
                print(f"[LIVE INIT] Priming last_message_id to {newest_id}, ignoring existing signals.")
                return [], newest_id
            else:
                return [], None

        # --- NORMAL RUN: only process messages newer than last_message_id ---
        signals = []
        new_last_id = last_message_id

        for msg in messages:
            if not msg or not msg.message:
                continue

            if "PREMIUM SIGNAL" in msg.message and msg.id > last_message_id:
                signal = parse_signal(msg.message)
                if signal:
                    signals.append(signal)
                    if msg.id > new_last_id:
                        new_last_id = msg.id

        # Return at most n_signals newest signals
        result_signals = signals[-n_signals:] if signals else []
        return result_signals, new_last_id

    except Exception as e:
        print(f"[FETCH ERROR] {e}")
        import traceback
        traceback.print_exc()
        return [], last_message_id

def fetch_signals_from_file(n_signals=1):
    """
    Read last X signals from telegram_messages.txt.

    Expected format:
    - One full Telegram message per block.
    - Blocks separated by one blank line.
    - Each signal block contains 'PREMIUM SIGNAL' and matches parse_signal().
    """
    try:
        with open("telegram_messages.txt", "r", encoding="utf-8") as f:
            content = f.read().strip()
    except FileNotFoundError:
        print("telegram_messages.txt not found.")
        return []

    blocks = re.split(r"\n\s*\n", content)
    signals = []

    for block in blocks:
        if "PREMIUM SIGNAL" not in block:
            continue
        sig = parse_signal(block)
        if sig:
            signals.append(sig)

    if not signals:
        print("No valid signals found in telegram_messages.txt.")
        return []

    return signals[-n_signals:]


# ------------------------------------------------
# Stop-loss clamp
# ------------------------------------------------

def clamp_stoploss(signal, stop_loss_percent):
    """
    Clamp signal['stoploss'] so it is at most stop_loss_percent away from signal['entry'].

    - If the signal SL is tighter (closer to entry), we keep it.
    - If it is wider (too far), we clamp to the allowed band.

    LONG:
      allowed_min = entry * (1 - pct)
      if sl < allowed_min -> clamp up to allowed_min

    SHORT:
      allowed_max = entry * (1 + pct)
      if sl > allowed_max -> clamp down to allowed_max
    """
    try:
        direction = str(signal.get("direction", "")).upper()
        entry = float(signal["entry"])
        sl = float(signal["stoploss"])
    except Exception:
        # If anything is missing or malformed, don't clamp.
        return

    pct = float(stop_loss_percent) / 100.0
    if pct <= 0:
        return

    if direction == "LONG":
        allowed_sl = entry * (1.0 - pct)
        if sl < allowed_sl:
            print(f"[SL CLAMP] LONG SL {sl:.6f} too far from entry {entry:.6f}, "
                  f"clamping to {allowed_sl:.6f}")
            signal["stoploss"] = allowed_sl
    elif direction == "SHORT":
        allowed_sl = entry * (1.0 + pct)
        if sl > allowed_sl:
            print(f"[SL CLAMP] SHORT SL {sl:.6f} too far from entry {entry:.6f}, "
                  f"clamping to {allowed_sl:.6f}")
            signal["stoploss"] = allowed_sl
    else:
        # Unknown direction – don't touch
        return


# ------------------------------------------------
# Main loop
# ------------------------------------------------

async def main_loop():
    print("×10 BOT STARTED – Waiting for new signals...\n")
    traded_hashes = set()
    trade_count = 0
    max_trades = int(config.get("max_trades_per_day", 20))
    max_open_pos = int(config.get("max_open_positions", 14))
    max_lev = int(config.get("max_leverage", 10))
    dry_run = bool(config.get("dry_run_mode", False))
    stop_loss_pct = float(config.get("stop_loss_percent", 1.8))

    last_message_id = None

    # Optional: set up live Telegram (only if requested and not in test mode)
    if use_live:
        creds = read_credentials("credentials.txt")
        if "api_id" not in creds or "api_hash" not in creds:
            print("Missing api_id/api_hash in credentials.txt – cannot use LIVE Telegram.")
        else:
            init_telegram(int(creds["api_id"]), creds["api_hash"])
            try:
                if bot_telegram.client is not None and not bot_telegram.client.is_connected():
                    print("Connecting to Telegram...")
                    await bot_telegram.client.start()
                    print("Telegram connected.")
            except Exception as e:
                print(f"[TELEGRAM START ERROR] {e}")
                import traceback
                traceback.print_exc()

    while True:
        try:
            if trade_count >= max_trades:
                print(f"Max trades reached ({max_trades}). Stopping for now.")
                break

            balance = await get_balance()

            # Decide trade size
            if config.get("use_absolute_usdt", False):
                usdt_amount = float(config.get("absolute_usdt_per_trade", 5.0))
            else:
                usdt_amount = balance * (config["usdt_per_trade_percent"] / 100.0)

            if test:
                usdt_amount = max(1.0, min(9.0, usdt_amount))

            if usdt_amount <= 0:
                print("Computed trade size <= 0, skipping loop...")
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            open_pos = await get_open_positions_count()
            if open_pos >= max_open_pos:
                print(
                    f"Max open positions reached "
                    f"({open_pos}/{max_open_pos}) – waiting..."
                )
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            # ---- FETCH SIGNAL ----
            if use_live and not test:
                # LIVE Telegram
                signals, last_message_id = await fetch_live_signals(
                    limit=10, n_signals=3, last_message_id=last_message_id
                )
            else:
                # File-based (test or normal)
                signals = fetch_signals_from_file(n_signals=3)

            new_signal = None
            for sig in signals:
                h = hashlib.md5(sig["raw_text"].encode()).hexdigest()
                if h not in traded_hashes:
                    new_signal = (sig, h)
                    break

            if not new_signal:
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            signal, h = new_signal

            # ---- LEVERAGE CAP ----
            signal_lev = int(signal.get("leverage", max_lev))
            lev_cap = 2 if test else max_lev
            lev = min(signal_lev, lev_cap)

            # ---- SL CLAMP ----
            clamp_stoploss(signal, stop_loss_pct)

            print(
                f"NEW SIGNAL → {signal['symbol']} {signal['direction']} "
                f"{lev}x – ${usdt_amount:.2f}"
            )

            await execute_trade(
                client_bingx,
                signal,
                usdt_amount,
                leverage=lev,
                config=config,
                dry_run=dry_run,
            )

            traded_hashes.add(h)
            trade_count += 1
            print(f"Trade executed – unique this run: {len(traded_hashes)} "
                  f"(total trades: {trade_count})\n")

            await asyncio.sleep(config["check_interval_seconds"])

        except Exception as e:
            print(f"[ERROR] {e}\n")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main_loop())
