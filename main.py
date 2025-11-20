# main.py – MULTI-MODE BOT
# LIVE: scrapes Telegram channel and trades on BingX
# DRY-RUN: uses telegram_messages.txt, $5 @ 1x, max 3 trades

import asyncio
import re
from datetime import datetime

from api import bingx_api_request
from bot_telegram import parse_signal, init_telegram, read_credentials
import bot_telegram
from trade import execute_trade
from telethon.tl.types import InputPeerChannel
from config import get_config


# ==============================
# Helpers
# ==============================

async def fetch_live_signals(limit=10, n_signals=1, last_message_id=None):
    """
    Fetch latest PREMIUM SIGNAL(S) from Telegram channel using Telethon.
    Used ONLY in LIVE mode.
    """
    try:
        if bot_telegram.client is None:
            print("[FETCH ERROR] Telegram client not initialized. Please restart the bot.")
            return [], last_message_id

        if not bot_telegram.client.is_connected():
            print("[FETCH ERROR] Telegram client not connected. Attempting to reconnect...")
            try:
                await bot_telegram.client.connect()
            except Exception as e:
                print(f"[FETCH ERROR] Failed to reconnect: {e}")
                return [], last_message_id

        # Read channel details from file
        with open('channel_details.txt') as f:
            lines = f.readlines()
            channel_id = int(lines[0].split(':')[1].strip())
            access_hash = int(lines[1].split(':')[1].strip())

        entity = InputPeerChannel(channel_id, access_hash)
        messages = await bot_telegram.client.get_messages(entity, limit=limit)

        signals = []
        new_last_id = last_message_id

        for msg in messages:
            if msg.message and "PREMIUM SIGNAL" in msg.message:
                if last_message_id is None or msg.id > last_message_id:
                    signal = parse_signal(msg.message)
                    if signal:
                        signals.append(signal)
                        if new_last_id is None or msg.id > new_last_id:
                            new_last_id = msg.id

        result_signals = signals[-n_signals:] if signals else []
        return result_signals, new_last_id
    except Exception as e:
        print(f"[FETCH ERROR] {e}")
        import traceback
        traceback.print_exc()
        return [], last_message_id


def fetch_signals_from_file(n_signals=1):
    """
    Fetch last PREMIUM SIGNAL(S) from telegram_messages.txt.
    Used for DRY-RUN mode and TestY mode.
    """
    try:
        with open('telegram_messages.txt', 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print("telegram_messages.txt not found.")
        return []

    # Rough split on "Message ID:" pattern used in your logs
    blocks = re.split(r'Message ID:', content)[1:]
    messages = []
    for block in blocks:
        msg_text = re.search(r'Text: (.*?)(?=Message ID:|$)', block, re.DOTALL)
        if msg_text:
            clean_text = msg_text.group(1).strip()
            if "PREMIUM SIGNAL" in clean_text:
                messages.append(clean_text)

    signals = []
    for msg in messages[-n_signals:]:
        sig = parse_signal(msg)
        if sig:
            signals.append(sig)

    if not signals:
        print("No valid signals found in telegram_messages.txt.")
    return signals


# ==============================
# MAIN
# ==============================

async def main():
    # --- LOAD CONFIG ---
    config = get_config()

    print("\n" + "=" * 70)
    print("TRADING BOT – MULTI MODE")
    print("=" * 70)
    print(f"Loaded config:")
    print(f"  usdt_per_trade       : {config.get('usdt_per_trade', 'N/A')}")
    print(f"  max_trades_per_day   : {config.get('max_trades_per_day', 'N/A')}")
    print(f"  check_interval_second: {config.get('check_interval_seconds', 'N/A')}")
    print(f"  position_mode        : {config.get('position_mode', 'N/A')}")
    print(f"  order_type           : {config.get('order_type', 'N/A')}")
    print(f"  max_allowed_leverage : {config.get('max_allowed_leverage', 'N/A')}")
    print(f"  dry_run_mode (config): {config.get('dry_run_mode', False)}")

    print("\n" + "=" * 70)
    print("TRADING BOT – SELECT MODE")
    print("=" * 70)
    print("1. Normal Plan Mode (uses config)")
    print("2. Test Mode (Custom Amount + Leverage) – RUNS IN LOOP")
    print("3. TestY Mode (Custom + Last X Signals from telegram_messages.txt)")
    mode = input("Choose (1/2/3): ").strip()

    # --- BASIC MODE SETUP ---
    if mode == "1":
        usdt_amount = float(config.get('usdt_per_trade', 5.0))
        max_trades = int(config.get('max_trades_per_day', 10))
        print(f"NORMAL MODE: {usdt_amount} USDT per trade, Max {max_trades} trades/day")
        print(f"  Max allowed leverage: {config.get('max_allowed_leverage', 10)}x")
        print(f"  Position mode: {config.get('position_mode', 'Isolated')}")
        print(f"  Order type: {config.get('order_type', 'LIMIT')}")

    elif mode == "2":
        usdt_amount = float(input("Enter test amount (USDT): ").strip())
        leverage = int(input("Enter test leverage: ").strip())
        max_trades = int(input("Enter max trades per day: ").strip())
        print(f"TEST MODE: {usdt_amount} USDT, {leverage}x, Max {max_trades} trades/day (LOOP)")

    elif mode == "3":
        usdt_amount = float(input("Enter test amount (USDT): ").strip())
        leverage = int(input("Enter test leverage: ").strip())
        x_signals = int(input("Enter number of last signals (X): ").strip())
        max_trades = x_signals
        print(f"TESTY MODE: {usdt_amount} USDT, {leverage}x, Last {x_signals} signals from telegram_messages.txt")

        signals = fetch_signals_from_file(n_signals=x_signals)
        if not signals:
            print("No valid signals found.")
            return
    else:
        print("Invalid choice")
        return

    # --- CHOOSE LIVE vs DRY-RUN ---
    if config.get('dry_run_mode', False):
        dry_run = True
        print("\n⚠️  DRY-RUN MODE ENABLED IN CONFIG - No real trades will be executed")
    else:
        live_choice = input("Run LIVE or DRY-RUN? (live/dry) [dry]: ").strip().lower()
        dry_run = (live_choice != "live")

    mode_name = "LIVE" if not dry_run else "DRY-RUN"
    print(f"\nRUNNING IN {mode_name} MODE")

    # --- DRY-RUN HARD SAFETY CLAMPS ---
    if dry_run:
        # Never more than 3 trades in DRY-RUN, no matter what config/mode says
        max_trades = min(max_trades, 3)
        print(f"[DRY-RUN SAFE] Max trades capped at {max_trades} per run.")

    # --- TELEGRAM + BINGX SETUP ---
    if not dry_run:
        # LIVE: connect to Telegram AND BingX
        print("\n=== TELEGRAM CONNECTION (LIVE signal scraping) ===")
        creds = read_credentials('credentials.txt')
        if 'api_id' not in creds or 'api_hash' not in creds:
            print("Missing Telegram credentials (api_id/api_hash) in credentials.txt")
            return

        init_telegram(int(creds['api_id']), creds['api_hash'])

        phone = input("Enter Phone Number (with +): ").strip()
        if not phone:
            print("Phone number is required for Telegram connection!")
            return

        try:
            print("\nConnecting to Telegram...")
            if not bot_telegram.client.is_connected():
                await bot_telegram.client.start(phone=lambda: phone)
            else:
                print("Telegram already connected (using existing session)")
            print("Telegram connected!")

            # Test channel access
            try:
                with open('channel_details.txt') as f:
                    lines = f.readlines()
                    channel_id = int(lines[0].split(':')[1].strip())
                    access_hash = int(lines[1].split(':')[1].strip())
                entity = InputPeerChannel(channel_id, access_hash)
                test_msg = await bot_telegram.client.get_messages(entity, limit=1)
                print(f"✓ Channel access verified ({len(test_msg)} messages accessible)")
            except Exception as e:
                print(f"⚠️  Channel access test failed: {e}")
                print("Continuing anyway, but verify channel access...")
        except Exception as e:
            print(f"Telegram login failed: {e}")
            import traceback
            traceback.print_exc()
            return

        print("\n=== LIVE MODE: BINGX LOGIN REQUIRED ===")
        if 'bingx_api_key' not in creds:
            print("Missing bingx_api_key in credentials.txt")
            return

        secret_key = input("Enter BingX Secret Key: ").strip()
        if not secret_key:
            print("BingX Secret Key is required for LIVE mode!")
            return

        client_bingx = {
            'api_key': creds['bingx_api_key'],
            'secret_key': secret_key,
            'base_url': 'https://open-api.bingx.com'
        }
    else:
        # DRY-RUN: NO TELEGRAM LOGIN, dummy client
        print("\n[DRY-RUN] Skipping Telegram login – using telegram_messages.txt instead.")
        client_bingx = {
            'api_key': 'dummy',
            'secret_key': 'dummy',
            'base_url': 'https://test.com'
        }

    # ==============================
    # MODE 1 & 2 – MAIN LOOP
    # ==============================
    daily_trades = 0
    last_message_id = None  # for LIVE to avoid replaying old messages

    while mode in ["1", "2"]:
        try:
            if daily_trades >= max_trades:
                print(f"Max trades reached ({max_trades}). Exiting loop.")
                break

            # --- FETCH SIGNALS ---
            if not dry_run:
                # LIVE – scrape channel
                try:
                    signals, last_message_id = await fetch_live_signals(
                        limit=10,
                        n_signals=1,
                        last_message_id=last_message_id
                    )
                except Exception as e:
                    print(f"[SIGNAL FETCH ERROR] {e}")
                    import traceback
                    traceback.print_exc()
                    await asyncio.sleep(config.get('check_interval_seconds', 8))
                    continue
            else:
                # DRY-RUN – file-based
                signals = fetch_signals_from_file(n_signals=1)

            if not signals:
                print("No new signals. Waiting...")
                await asyncio.sleep(config.get('check_interval_seconds', 8))
                continue

            # --- EXECUTE TRADES ---
            for signal in signals:
                if daily_trades >= max_trades:
                    break

                signal_leverage = signal.get('leverage', 0)

                # Respect global leverage cap from config in LIVE mode
                if not dry_run:
                    max_allowed = int(config.get('max_allowed_leverage', 50))
                    if signal_leverage > max_allowed:
                        print(
                            f"⚠️  Signal leverage {signal_leverage}x exceeds max allowed {max_allowed}x. Skipping signal."
                        )
                        continue

                # Decide effective USDT & leverage
                if dry_run:
                    # HARD CLAMP: DRY-RUN is always $5 @ 1x
                    safe_usdt = 5.0
                    usdt_eff = min(usdt_amount, safe_usdt)
                    lev_eff = 1
                    print(f"[DRY-RUN SAFE] Using ${usdt_eff:.2f} at {lev_eff}x (clamped)")
                else:
                    # LIVE
                    if mode == "2":
                        # Test Mode LIVE: use chosen test leverage
                        lev_eff = leverage
                        usdt_eff = usdt_amount
                    else:
                        # Normal Mode LIVE: use config usdt + signal leverage (capped above)
                        lev_eff = signal_leverage
                        usdt_eff = usdt_amount

                print(
                    f"\n--- {'EXECUTING' if not dry_run else 'SIMULATING'} "
                    f"TRADE {daily_trades + 1}/{max_trades} ---"
                )
                print(f"Signal: {signal['symbol']} {signal['direction']} {signal_leverage}x")

                await execute_trade(
                    client_bingx,
                    signal,
                    usdt_eff,
                    leverage=lev_eff,
                    config=config,
                    dry_run=dry_run
                )

                daily_trades += 1

            await asyncio.sleep(config.get('check_interval_seconds', 8))

        except KeyboardInterrupt:
            print("\nBot stopped by user")
            break
        except Exception as e:
            print(f"[MAIN LOOP ERROR] {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(60)

    # ==============================
    # MODE 3 – TestY (from file once)
    # ==============================
    if mode == "3":
        for i, signal in enumerate(signals):
            if i >= max_trades:
                break

            # DRY-RUN clamps still apply
            if dry_run:
                safe_usdt = 5.0
                usdt_eff = min(usdt_amount, safe_usdt)
                lev_eff = 1
                print(f"[DRY-RUN SAFE] Using ${usdt_eff:.2f} at {lev_eff}x (clamped)")
            else:
                usdt_eff = usdt_amount
                lev_eff = leverage

            print(
                f"\n--- {'EXECUTING' if not dry_run else 'SIMULATING'} "
                f"TRADE {i + 1}/{max_trades} ---"
            )
            print(f"Signal: {signal['symbol']} {signal['direction']} {signal.get('leverage', 0)}x")

            await execute_trade(
                client_bingx,
                signal,
                usdt_eff,
                leverage=lev_eff,
                config=config,
                dry_run=dry_run
            )

    print(f"\nMODE COMPLETE – ALL {'EXECUTED' if not dry_run else 'SIMULATED'}")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
