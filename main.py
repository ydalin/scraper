# main.py – SIMPLE LIVE/FILE BOT USING CONFIG.PY ONLY

import asyncio
import hashlib
from datetime import datetime

from api import bingx_api_request
from bot_telegram import parse_signal, init_telegram, read_credentials
import bot_telegram
from telethon.tl.types import InputPeerChannel
from config import get_config, prompt_config
from trade import execute_trade


async def get_open_positions_count(client_bingx: dict) -> int:
    try:
        resp = await bingx_api_request(
            "GET",
            "/openApi/swap/v2/user/positions",
            client_bingx["api_key"],
            client_bingx["secret_key"],
        )
        if resp.get("code") == 0:
            data = resp.get("data") or []
            if isinstance(data, list):
                return len(data)
            if isinstance(data, dict) and data:
                return 1
    except Exception as e:
        print(f"[POS COUNT ERROR] {e}")
    return 0


def load_config_interactive():
    print("\n" + "=" * 70)
    print("TRADING BOT – CONFIGURATION")
    print("=" * 70)
    choice = input("Load config from file (config.py) or configure now? (load/configure) [load]: ").strip().lower()
    if choice == "configure":
        cfg = prompt_config()
        print("\nUsing interactive configuration:")
    else:
        cfg = get_config()
        print("\nLoaded configuration from config.py:")
    print(f"  USDT per trade       : {cfg['usdt_per_trade']}")
    print(f"  Max trades per day   : {cfg['max_trades_per_day']}")
    print(f"  Check interval       : {cfg['check_interval_seconds']}s")
    print(f"  Position mode        : {cfg['position_mode']}")
    print(f"  Order type           : {cfg['order_type']}")
    print(f"  Max allowed leverage : {cfg['max_allowed_leverage']}x")
    print(f"  Dry run mode         : {cfg['dry_run_mode']}")
    return cfg


async def fetch_new_signals_live(last_message_id=None, limit=30):
    """
    Fetch new PREMIUM SIGNAL messages from Telegram using Telethon.

    Expects channel_details.txt to contain:
      channel_id: <id>
      access_hash: <hash>
    """
    try:
        if bot_telegram.client is None:
            print("[FETCH ERROR] Telegram client not initialized.")
            return [], last_message_id

        if not bot_telegram.client.is_connected():
            print("[FETCH] Telegram client not connected; reconnecting...")
            await bot_telegram.client.connect()

        with open("channel_details.txt") as f:
            lines = f.readlines()
            channel_id = int(lines[0].split(":")[1].strip())
            access_hash = int(lines[1].split(":")[1].strip())

        entity = InputPeerChannel(channel_id, access_hash)
        messages = await bot_telegram.client.get_messages(entity, limit=limit)

        signals = []
        new_last_id = last_message_id

        # Process from oldest to newest so we trade in order
        for msg in reversed(messages):
            if not msg.message:
                continue
            text = msg.message
            if "PREMIUM SIGNAL" not in text:
                continue

            if last_message_id is not None and msg.id <= last_message_id:
                continue

            sig = parse_signal(text)
            if sig:
                signals.append(sig)
                if new_last_id is None or msg.id > new_last_id:
                    new_last_id = msg.id

        return signals, new_last_id
    except Exception as e:
        print(f"[FETCH ERROR] {e}")
        return [], last_message_id


def read_signals_from_file(path="telegram_messages.txt", max_signals=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"[FILE] {path} not found.")
        return []

    # Very simple: split on blank lines and only keep blocks with PREMIUM SIGNAL
    blocks = content.split("\n\n")
    signals = []
    for block in blocks:
        text = block.strip()
        if not text:
            continue
        if "PREMIUM SIGNAL" not in text:
            continue
        sig = parse_signal(text)
        if sig:
            signals.append(sig)
    if max_signals is not None:
        return signals[-max_signals:]
    return signals


async def main():
    print("\n" + "=" * 70)
    print("   BINGX ×10 FUTURES BOT – LIVE MONEY")
    print("=" * 70)

    config = load_config_interactive()

    # === MODE: tiny test or normal ===
    tiny_choice = input("Tiny test mode ($1–$9 + 1–2x) or Normal mode? (t/n) [n]: ").strip().lower()
    tiny_mode = (tiny_choice == "t")
    if tiny_mode:
        print("   → TINY TEST MODE – $1–$9 + up to 2x leverage")
    else:
        print("   → NORMAL MODE – config USDT per trade + config leverage cap")
    print("=" * 70)

    # === DRY RUN / LIVE ===
    if config["dry_run_mode"]:
        dry_run = True
        print("\n⚠️  DRY-RUN MODE ENABLED IN CONFIG – no real trades will be sent.")
    else:
        live_choice = input("Run LIVE or DRY-RUN? (live/dry) [live]: ").strip().lower()
        dry_run = (live_choice != "live")

    mode_name = "LIVE" if not dry_run else "DRY-RUN"
    print(f"RUNNING IN {mode_name} MODE")

    # === SIGNAL SOURCE: LIVE TELEGRAM OR FILE ===
    src_choice = input("Use LIVE Telegram scraping or local file? (live/file) [file]: ").strip().lower()
    use_live = (src_choice == "live")

    # === TELEGRAM INITIALIZATION (for LIVE signal fetching) ===
    if use_live:
        print("\n=== TELEGRAM CONNECTION ===")
        creds = read_credentials("credentials.txt")
        if "api_id" not in creds or "api_hash" not in creds:
            print("Missing Telegram credentials (api_id/api_hash) in credentials.txt")
            return

        init_telegram(int(creds["api_id"]), creds["api_hash"])

        phone = input("Enter Phone Number (with +): ").strip()
        if not phone:
            print("Phone number is required for Telegram connection!")
            return

        try:
            await bot_telegram.client.connect()
            if not await bot_telegram.client.is_user_authorized():
                await bot_telegram.client.send_code_request(phone)
                code = input("Enter the code you received on Telegram: ").strip()
                await bot_telegram.client.sign_in(phone, code)
            print("Telegram connected.")
        except Exception as e:
            print(f"Telegram login failed: {e}")
            return
    else:
        creds = {}

    # === BINGX CLIENT SETUP ===
    if dry_run:
        client_bingx = {
            "api_key": "dummy",
            "secret_key": "dummy",
            "base_url": "https://test.com",
        }
    else:
        print("\n=== BINGX – SECRET KEY REQUIRED ===")
        secret_key = input("Enter BingX Secret Key: ").strip()
        api_key = config.get("bingx_api_key", "").strip()

        if not secret_key or not api_key:
            print("BingX Secret Key AND bingx_api_key in config.py are required for LIVE mode!")
            return

        client_bingx = {
            "api_key": api_key,
            "secret_key": secret_key,
            "base_url": "https://open-api.bingx.com",
        }

    # === MAIN LOOP (LIVE) or ONE-SHOT (FILE) ===
    traded_hashes = set()
    daily_trades = 0
    last_reset = datetime.now().date()
    last_message_id = None

    if not use_live:
        # FILE MODE: run once over the file
        signals = read_signals_from_file("telegram_messages.txt")
        if not signals:
            print("No valid signals found in telegram_messages.txt.")
            return

        print(f"Found {len(signals)} signal(s) in file.")
        for idx, sig in enumerate(signals, start=1):
            h = hashlib.md5(sig["raw_text"].encode("utf-8")).hexdigest()
            if h in traded_hashes:
                continue

            # Determine USDT per trade
            if tiny_mode:
                usdt_amount = min(9.0, max(1.0, config["usdt_per_trade"]))
            else:
                usdt_amount = config["usdt_per_trade"]

            # Clamp leverage
            sig_lev = sig.get("leverage") or 1
            try:
                sig_lev = int(sig_lev)
            except Exception:
                sig_lev = 1

            max_lev = config.get("max_allowed_leverage", 10)
            try:
                max_lev = int(max_lev)
            except Exception:
                max_lev = 10

            if tiny_mode:
                lev_cap = min(2, max_lev)
            else:
                lev_cap = max_lev
            lev = max(1, min(sig_lev, lev_cap))

            print(f"FILE SIGNAL {idx}: {sig['symbol']} {sig['direction']} {lev}x – ${usdt_amount:.2f}")
            await execute_trade(
                client_bingx,
                sig,
                usdt_amount,
                leverage=lev,
                config=config,
                dry_run=dry_run,
            )
            traded_hashes.add(h)
        print("FILE MODE COMPLETE.")
        return

    # LIVE MODE LOOP
    print("\nLIVE MODE STARTED – waiting for new signals...")
    while True:
        try:
            # Daily reset of counter
            today = datetime.now().date()
            if today != last_reset:
                daily_trades = 0
                last_reset = today
                traded_hashes.clear()
                print(f"=== Daily reset – {today} ===")

            if daily_trades >= config["max_trades_per_day"]:
                print(f"Max trades reached ({config['max_trades_per_day']}). Sleeping 1 hour...")
                await asyncio.sleep(3600)
                continue

            open_count = await get_open_positions_count(client_bingx)
            if open_count >= config["max_open_positions"]:
                print(f"[LIMIT] Open positions {open_count} ≥ max_open_positions {config['max_open_positions']}.")
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            signals, last_message_id = await fetch_new_signals_live(
                last_message_id=last_message_id, limit=30
            )
            if not signals:
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            # Trade only the first NEW signal this loop
            sig = signals[0]
            h = hashlib.md5(sig["raw_text"].encode("utf-8")).hexdigest()
            if h in traded_hashes:
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            # Determine USDT per trade
            if tiny_mode:
                usdt_amount = min(9.0, max(1.0, config["usdt_per_trade"]))
            else:
                usdt_amount = config["usdt_per_trade"]

            # Clamp leverage
            sig_lev = sig.get("leverage") or 1
            try:
                sig_lev = int(sig_lev)
            except Exception:
                sig_lev = 1

            max_lev = config.get("max_allowed_leverage", 10)
            try:
                max_lev = int(max_lev)
            except Exception:
                max_lev = 10

            if tiny_mode:
                lev_cap = min(2, max_lev)
            else:
                lev_cap = max_lev
            lev = max(1, min(sig_lev, lev_cap))

            print(f"NEW SIGNAL → {sig['symbol']} {sig['direction']} {lev}x – ${usdt_amount:.2f}")
            await execute_trade(
                client_bingx,
                sig,
                usdt_amount,
                leverage=lev,
                config=config,
                dry_run=dry_run,
            )
            traded_hashes.add(h)
            daily_trades += 1
            print(f"Trade executed – unique this run: {len(traded_hashes)} (total today: {daily_trades})")

            await asyncio.sleep(config["check_interval_seconds"])
        except Exception as e:
            print(f"[ERROR] {e}")
            await asyncio.sleep(30)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
