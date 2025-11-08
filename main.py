# main.py – FINAL: LIVE TELEGRAM + FILE + ALL MODES
import asyncio
import re
from datetime import datetime
from api import bingx_api_request
from bot_telegram import parse_signal, init_telegram, read_credentials
import bot_telegram
from trade import execute_trade
from telethon.tl.types import InputPeerChannel

# === HARD CODED START DATE ===
START_DATE = datetime(2025, 11, 6).date()
SAFE_MODE_DAYS = 7
USE_SAFE_MODE = (datetime.now().date() - START_DATE).days < SAFE_MODE_DAYS

# === DEFAULT SETTINGS ===
SAFE_USDT = 1000.0
SAFE_LEVERAGE = 20
SAFE_MAX_TRADES = 3

FULL_USDT = 6500.0
FULL_LEVERAGE = 50
FULL_MAX_TRADES = 7

CHECK_INTERVAL = 30

async def fetch_live_signals(limit=10, n_signals=1):
    """Fetch latest PREMIUM SIGNALS from Telegram channel"""
    try:
        with open('channel_details.txt') as f:
            lines = f.readlines()
            channel_id = int(lines[0].split(':')[1].strip())
            access_hash = int(lines[1].split(':')[1].strip())

        entity = InputPeerChannel(channel_id, access_hash)
        messages = await bot_telegram.client.get_messages(entity, limit=limit)

        signals = []
        for msg in messages:
            if msg.message and "PREMIUM SIGNAL" in msg.message:
                signal = parse_signal(msg.message)
                if signal:
                    signals.append(signal)
        return signals[-n_signals:] if signals else []
    except Exception as e:
        print(f"[FETCH ERROR] {e}")
        return []

async def main():
    print("TRADING BOT – SELECT MODE")
    print("1. Normal Plan Mode")
    print("2. Test Mode (Custom Amount + Leverage) – RUNS IN LOOP")
    print("3. TestY Mode (Custom + Last X Signals from telegram_messages.txt)")
    mode = input("Choose (1/2/3): ").strip()

    # === MODE 1: NORMAL PLAN ===
    if mode == "1":
        usdt_amount = SAFE_USDT if USE_SAFE_MODE else FULL_USDT
        leverage = SAFE_LEVERAGE if USE_SAFE_MODE else FULL_LEVERAGE
        max_trades = SAFE_MAX_TRADES if USE_SAFE_MODE else FULL_MAX_TRADES
        print(f"NORMAL MODE: {usdt_amount} USDT, {leverage}x, Max {max_trades} trades/day")

    # === MODE 2: TEST MODE (LOOP) ===
    elif mode == "2":
        usdt_amount = float(input("Enter test amount (USDT): ").strip())
        leverage = int(input("Enter test leverage: ").strip())
        max_trades = int(input("Enter max trades per day: ").strip())
        print(f"TEST MODE: {usdt_amount} USDT, {leverage}x, Max {max_trades} trades/day (LOOP)")

    # === MODE 3: TESTY MODE (FROM FILE) ===
    elif mode == "3":
        usdt_amount = float(input("Enter test amount (USDT): ").strip())
        leverage = int(input("Enter test leverage: ").strip())
        x_signals = int(input("Enter number of last signals (X): ").strip())
        max_trades = x_signals
        print(f"TESTY MODE: {usdt_amount} USDT, {leverage}x, Last {x_signals} signals from telegram_messages.txt")

        try:
            with open('telegram_messages.txt', 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            print("telegram_messages.txt not found!")
            return

        blocks = re.split(r'Message ID:', content)[1:]
        messages = []
        for block in blocks:
            msg_text = re.search(r'Text: (.*?)(?=Message ID:|$)', block, re.DOTALL)
            if msg_text:
                clean_text = msg_text.group(1).strip()
                if "PREMIUM SIGNAL" in clean_text:
                    messages.append(clean_text)

        print(f"Found {len(messages)} PREMIUM SIGNAL message(s)")

        signals = []
        for msg in messages[-x_signals:]:
            signal = parse_signal(msg)
            if signal:
                signals.append(signal)
                print(f"Parsed: {signal['symbol']} {signal['direction']} {signal['leverage']}x")

        if not signals:
            print("No valid signals found.")
            return
    else:
        print("Invalid choice")
        return

    # === PROMPT FOR LIVE OR DRY-RUN ===
    live_choice = input("Run LIVE or DRY-RUN? (live/dry): ").strip().lower()
    dry_run = (live_choice != "live")
    mode_name = "LIVE" if not dry_run else "DRY-RUN"
    print(f"RUNNING IN {mode_name} MODE")

    # === LOGIN REQUIRED FOR LIVE TRADES ===
    if not dry_run:
        print("\n=== LIVE MODE: LOGIN REQUIRED ===")
        phone = input("Enter Phone Number (with +): ").strip()
        secret_key = input("Enter BingX Secret Key: ").strip()

        if not phone or not secret_key:
            print("Phone and Secret Key are required for LIVE mode!")
            return

        creds = read_credentials('credentials.txt')
        if 'api_id' not in creds or 'api_hash' not in creds or 'bingx_api_key' not in creds:
            print("Missing credentials in credentials.txt")
            return

        client_bingx = {
            'api_key': creds['bingx_api_key'],
            'secret_key': secret_key,
            'base_url': 'https://open-api.bingx.com'
        }

        init_telegram(int(creds['api_id']), creds['api_hash'])
        try:
            print("\nConnecting to Telegram...")
            await bot_telegram.client.start(phone=lambda: phone)
            print("Telegram connected!")
        except Exception as e:
            print(f"Telegram login failed: {e}")
            return
    else:
        client_bingx = {
            'api_key': 'dummy',
            'secret_key': 'dummy',
            'base_url': 'https://test.com'
        }

    # === MAIN LOOP (MODES 1 & 2) ===
    daily_trades = 0
    last_reset = datetime.now().date()

    while mode in ["1", "2"]:
        try:
            if datetime.now().date() != last_reset:
                daily_trades = 0
                last_reset = datetime.now().date()
                print(f"\nDaily reset – {last_reset}")

            if daily_trades >= max_trades:
                print(f"Max trades reached ({max_trades}). Sleeping 1 hour...")
                await asyncio.sleep(3600)
                continue

            signals = await fetch_live_signals(limit=10, n_signals=1)
            if not signals:
                print("No new signals. Waiting...")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for signal in signals:
                if daily_trades >= max_trades:
                    break
                print(f"\n--- {'EXECUTING' if not dry_run else 'SIMULATING'} TRADE {daily_trades+1}/{max_trades} ---")
                await execute_trade(client_bingx, signal, usdt_amount, dry_run=dry_run, custom_leverage=leverage)
                daily_trades += 1

            await asyncio.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"[MAIN LOOP ERROR] {e}")
            await asyncio.sleep(60)

    # === MODE 3: EXECUTE FROM FILE ===
    if mode == "3":
        for i, signal in enumerate(signals):
            if i >= max_trades:
                break
            print(f"\n--- {'EXECUTING' if not dry_run else 'SIMULATING'} TRADE {i+1}/{max_trades} ---")
            await execute_trade(client_bingx, signal, usdt_amount, dry_run=dry_run, custom_leverage=leverage)

    print(f"\nMODE COMPLETE – ALL {'EXECUTED' if not dry_run else 'SIMULATED'}")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")