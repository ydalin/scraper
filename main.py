# main.py – FINAL: LIVE TELEGRAM + FILE + ALL MODES
import asyncio
import re
from datetime import datetime
from api import bingx_api_request
from bot_telegram import parse_signal, init_telegram, read_credentials
import bot_telegram
from trade import execute_trade
from telethon.tl.types import InputPeerChannel
from config import get_config, prompt_config

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

# === DAILY LIMITS ===
DAILY_LOSS_LIMIT = -100.0  # Stop trading if PnL <= -100 USDT
DAILY_PROFIT_TARGET = 200.0  # Stop trading if PnL >= +200 USDT

async def get_total_pnl(client):
    """Get total unrealized PnL from BingX account"""
    try:
        resp = await bingx_api_request(
            'GET', '/openApi/swap/v2/user/balance',
            client['api_key'], client['secret_key'], client['base_url']
        )
        if resp.get('code') == 0:
            # Try different possible response structures
            data = resp.get('data', {})
            if isinstance(data, list) and len(data) > 0:
                return float(data[0].get('unrealizedProfit', 0.0))
            elif isinstance(data, dict):
                balance = data.get('balance', {})
                return float(balance.get('unrealizedProfit', 0.0))
        return 0.0
    except Exception as e:
        print(f"[PNL ERROR] {e}")
        return 0.0

async def fetch_live_signals(limit=10, n_signals=100, last_message_id=None):
    """Fetch latest PREMIUM SIGNALS from Telegram channel"""
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
        
        with open('channel_details.txt') as f:
            lines = f.readlines()
            channel_id = int(lines[0].split(':')[1].strip())
            access_hash = int(lines[1].split(':')[1].strip())

        entity = InputPeerChannel(channel_id, access_hash)
        messages = await bot_telegram.client.get_messages(entity, limit=limit)

        signals = []
        new_last_id = last_message_id
        
        print(f"[DEBUG] Fetching with limit={limit}, n_signals={n_signals}, last_message_id={last_message_id}")
        print(f"[DEBUG] Retrieved {len(messages)} messages from Telegram")
        
        # If this is the first run (last_message_id is None), establish baseline
        # by finding the highest message ID without processing old signals
        if last_message_id is None:
            highest_id = None
            for msg in messages:
                if msg.message and "PREMIUM SIGNAL" in msg.message:
                    if highest_id is None or msg.id > highest_id:
                        highest_id = msg.id
            if highest_id is not None:
                new_last_id = highest_id
                print(f"[INIT] Baseline established: Only processing messages after ID {highest_id}")
                # Return empty signals on first run to avoid processing old signals
                return [], new_last_id
        
        # Process only NEW messages (ID > last_message_id)
        premium_signal_count = 0
        for msg in messages:
            if msg.message and "PREMIUM SIGNAL" in msg.message:
                premium_signal_count += 1
                print(f"[DEBUG] Found PREMIUM SIGNAL at message ID {msg.id} (baseline: {last_message_id})")
                # Only process messages newer than last_message_id
                if msg.id > last_message_id:
                    signal = parse_signal(msg.message)
                    if signal:
                        signals.append(signal)
                        print(f"[SIGNAL DETECTED] Message ID {msg.id}: {signal['symbol']} {signal['direction']} {signal['leverage']}x")
                    else:
                        # Signal parsing failed - this is expected for non-standard messages
                        # Show first 200 chars of message for debugging
                        msg_preview = msg.message[:200] if msg.message else "(empty)"
                        print(f"[SKIP] Message ID {msg.id}: Contains 'PREMIUM SIGNAL' but failed to parse")
                        print(f"       Preview: {msg_preview}...")
                    
                    # Update last_message_id even if parsing failed, so we don't reprocess the same messages
                    if new_last_id is None or msg.id > new_last_id:
                        new_last_id = msg.id
                else:
                    print(f"[DEBUG] Skipping message ID {msg.id} (not > {last_message_id})")
        
        print(f"[DEBUG] Total PREMIUM SIGNAL messages found: {premium_signal_count}")
        
        # Return signals and new last message ID for tracking
        print(f"[DEBUG] Total signals collected: {len(signals)}")
        for idx, sig in enumerate(signals):
            print(f"[DEBUG]   Signal {idx+1}: {sig['symbol']} {sig['direction']} {sig['leverage']}x")
        result_signals = signals[-n_signals:] if signals else []
        print(f"[DEBUG] Returning {len(result_signals)} signal(s) after slicing [-{n_signals}:]")
        return result_signals, new_last_id
    except Exception as e:
        print(f"[FETCH ERROR] {e}")
        import traceback
        traceback.print_exc()
        return [], last_message_id

async def main():
    # === LOAD CONFIGURATION ===
    print("\n" + "="*70)
    print("TRADING BOT – CONFIGURATION")
    print("="*70)
    config_choice = input("Load config from file or configure now? (load/configure) [load]: ").strip().lower()
    
    if config_choice == "configure":
        config = prompt_config()
    else:
        config = get_config()
        print(f"\nLoaded configuration from bot_config.json (or using defaults)")
        print(f"  USDT per trade: {config['usdt_per_trade']}")
        print(f"  Max trades/day: {config['max_trades_per_day']}")
        print(f"  Check interval: {config['check_interval_seconds']}s")
        print(f"  Position mode: {config['position_mode']}")
        print(f"  Order type: {config['order_type']}")
        print(f"  Max leverage: {config['max_allowed_leverage']}x")
        print(f"  Dry run: {config['dry_run_mode']}")
    
    print("\n" + "="*70)
    print("TRADING BOT – SELECT MODE")
    print("="*70)
    print("1. Normal Plan Mode (uses config)")
    print("2. Test Mode (Custom Amount + Leverage) – RUNS IN LOOP")
    print("3. TestY Mode (Custom + Last X Signals from telegram_messages.txt)")
    mode = input("Choose (1/2/3): ").strip()

    # === MODE 1: NORMAL PLAN (USES CONFIG) ===
    if mode == "1":
        usdt_amount = config['usdt_per_trade']
        max_trades = config['max_trades_per_day']
        # Leverage will come from signal, but we'll check against max_allowed_leverage
        print(f"NORMAL MODE: {usdt_amount} USDT per trade, Max {max_trades} trades/day")
        print(f"  Max allowed leverage: {config['max_allowed_leverage']}x")
        print(f"  Position mode: {config['position_mode']}")
        print(f"  Order type: {config['order_type']}")

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

    # === DRY-RUN MODE (from config or prompt) ===
    if config['dry_run_mode']:
        dry_run = True
        print("\n⚠️  DRY-RUN MODE ENABLED IN CONFIG - No real trades will be executed")
    else:
        live_choice = input("Run LIVE or DRY-RUN? (live/dry): ").strip().lower()
        dry_run = (live_choice != "live")
    
    mode_name = "LIVE" if not dry_run else "DRY-RUN"
    print(f"RUNNING IN {mode_name} MODE")

    # === TELEGRAM INITIALIZATION (REQUIRED FOR ALL MODES TO FETCH SIGNALS) ===
    print("\n=== TELEGRAM CONNECTION (Required for signal fetching) ===")
    creds = read_credentials('credentials.txt')
    if 'api_id' not in creds or 'api_hash' not in creds:
        print("Missing Telegram credentials (api_id/api_hash) in credentials.txt")
        return
    
    # Initialize Telegram client
    init_telegram(int(creds['api_id']), creds['api_hash'])
    
    # Get phone number for Telegram authentication (required for both modes)
    phone = input("Enter Phone Number (with +): ").strip()
    if not phone:
        print("Phone number is required for Telegram connection!")
        return
    
    try:
        print("\nConnecting to Telegram...")
        # For cloud: ensure session file exists and is valid
        if not bot_telegram.client.is_connected():
            await bot_telegram.client.start(phone=lambda: phone)
        else:
            print("Telegram already connected (using existing session)")
        print("Telegram connected!")
        
        # Test connection by fetching a message
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

    # === BINGX CLIENT SETUP (ONLY FOR LIVE MODE) ===
    if not dry_run:
        print("\n=== LIVE MODE: BINGX LOGIN REQUIRED ===")
        secret_key = input("Enter BingX Secret Key: ").strip()

        if not secret_key or 'bingx_api_key' not in creds:
            print("BingX Secret Key and API Key are required for LIVE mode!")
            return

        client_bingx = {
            'api_key': creds['bingx_api_key'],
            'secret_key': secret_key,
            'base_url': 'https://open-api.bingx.com'
        }
    else:
        client_bingx = {
            'api_key': 'dummy',
            'secret_key': 'dummy',
            'base_url': 'https://test.com'
        }

    # === MAIN LOOP (MODES 1 & 2) ===
    daily_trades = 0
    last_reset = datetime.now().date()
    last_message_id = None  # Track last processed message ID for cloud reliability
    traded_symbols = set()  # Track symbols traded today to prevent duplicates

    while mode in ["1", "2"]:
        try:
            # === DAILY RESET ===
            if datetime.now().date() != last_reset:
                daily_trades = 0
                last_reset = datetime.now().date()
                last_message_id = None  # Reset message tracking on new day
                traded_symbols.clear()  # Clear traded symbols on new day
                print(f"\n=== Daily reset – {last_reset} ===")

            # === CHECK DAILY TRADE LIMIT ===
            if daily_trades >= max_trades:
                print(f"Max trades reached ({max_trades}). Sleeping 1 hour...")
                await asyncio.sleep(3600)
                continue

            # === CHECK DAILY PnL LIMITS (only in LIVE mode) ===
            if not dry_run:
                current_pnl = await get_total_pnl(client_bingx)
                print(f"Current Daily PnL: {current_pnl:.2f} USDT")
                
                if current_pnl <= DAILY_LOSS_LIMIT:
                    print(f"⚠️  DAILY LOSS LIMIT REACHED: {current_pnl:.2f} USDT <= {DAILY_LOSS_LIMIT} USDT")
                    print("Stopping trading for today.")
                    break
                
                if current_pnl >= DAILY_PROFIT_TARGET:
                    print(f"✅ DAILY PROFIT TARGET REACHED: {current_pnl:.2f} USDT >= {DAILY_PROFIT_TARGET} USDT")
                    print("Stopping trading for today.")
                    break

            # === FETCH NEW SIGNALS ===
            try:
                signals, last_message_id = await fetch_live_signals(limit=50, n_signals=100, last_message_id=last_message_id)
                if signals:
                    print(f"[FETCH] Found {len(signals)} new signal(s)")
                else:
                    print(f"[FETCH] No new signals found (last_message_id: {last_message_id})")
            except Exception as e:
                print(f"[SIGNAL FETCH ERROR] {e}")
                import traceback
                traceback.print_exc()
                # Reconnect Telegram if connection lost
                try:
                    if bot_telegram.client is not None and not await bot_telegram.client.is_connected():
                        print("Reconnecting Telegram...")
                        await bot_telegram.client.connect()
                except Exception as reconnect_error:
                    print(f"[RECONNECT ERROR] {reconnect_error}")
                await asyncio.sleep(60)
                continue
            
            if not signals:
                print("No new signals. Waiting...")
                await asyncio.sleep(config['check_interval_seconds'])
                continue

            # === EXECUTE TRADES ===
            print(f"\n[TRADE LOOP] Processing {len(signals)} signal(s), daily_trades={daily_trades}/{max_trades}")
            for idx, signal in enumerate(signals, 1):
                print(f"\n[TRADE LOOP] Processing signal {idx}/{len(signals)}: {signal['symbol']}")
                
                if daily_trades >= max_trades:
                    print(f"[TRADE LOOP] Stopping: daily_trades ({daily_trades}) >= max_trades ({max_trades})")
                    break
                
                # === CHECK IF SYMBOL ALREADY TRADED TODAY ===
                symbol = signal['symbol']
                print(f"[TRADE LOOP] Checking if {symbol} already traded today (traded_symbols: {traded_symbols})")
                if symbol in traded_symbols:
                    print(f"⚠️  SKIPPING: {symbol} already traded today. Only one trade per symbol per day allowed.")
                    continue
                
                # === CHECK MAX ALLOWED LEVERAGE ===
                signal_leverage = signal.get('leverage', 0)
                print(f"[TRADE LOOP] Checking leverage: signal={signal_leverage}x, max_allowed={config['max_allowed_leverage']}x")
                if signal_leverage > config['max_allowed_leverage']:
                    print(f"⚠️  Signal leverage {signal_leverage}x exceeds max allowed {config['max_allowed_leverage']}x. Skipping signal.")
                    continue
                
                # === CHECK PnL BEFORE TRADE (only in LIVE mode) ===
                if not dry_run:
                    pre_trade_pnl = await get_total_pnl(client_bingx)
                    print(f"[TRADE LOOP] Current PnL: {pre_trade_pnl:.2f} USDT, limit: {DAILY_LOSS_LIMIT} USDT")
                    if pre_trade_pnl <= DAILY_LOSS_LIMIT:
                        print(f"⚠️  Cannot trade: PnL {pre_trade_pnl:.2f} USDT <= {DAILY_LOSS_LIMIT} USDT")
                        break
                
                print(f"\n--- {'EXECUTING' if not dry_run else 'SIMULATING'} TRADE {daily_trades+1}/{max_trades} ---")
                print(f"Signal: {signal['symbol']} {signal['direction']} {signal_leverage}x")
                
                # Use leverage from signal (already validated)
                leverage = signal_leverage
                
                await execute_trade(
                    client_bingx, signal, usdt_amount, 
                    dry_run=dry_run, 
                    custom_leverage=leverage,
                    config=config
                )
                
                # Add symbol to traded set (regardless of trade success, to prevent retries)
                traded_symbols.add(symbol)
                daily_trades += 1

            await asyncio.sleep(config['check_interval_seconds'])

        except KeyboardInterrupt:
            print("\nBot stopped by user")
            break
        except Exception as e:
            print(f"[MAIN LOOP ERROR] {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(60)  # Wait before retrying

    # === MODE 3: EXECUTE FROM FILE ===
    if mode == "3":
        for i, signal in enumerate(signals):
            if i >= max_trades:
                break
            print(f"\n--- {'EXECUTING' if not dry_run else 'SIMULATING'} TRADE {i+1}/{max_trades} ---")
            await execute_trade(client_bingx, signal, usdt_amount, dry_run=dry_run, custom_leverage=leverage, config=config)

    print(f"\nMODE COMPLETE – ALL {'EXECUTED' if not dry_run else 'SIMULATED'}")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
