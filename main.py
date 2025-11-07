# main.py – PROMPT FOR PHONE + CODE + SECRET KEY
import asyncio
from datetime import datetime
from api import bingx_api_request
from telegram import fetch_and_parse_telegram_signals, init_telegram, read_credentials, client as telegram_client
from trade import execute_trade

# === HARD CODED START DATE ===
START_DATE = datetime(2025, 11, 6).date()
SAFE_MODE_DAYS = 7
USE_SAFE_MODE = (datetime.now().date() - START_DATE).days < SAFE_MODE_DAYS

SAFE_USDT = 1000.0
SAFE_LEVERAGE = 20
SAFE_MAX_TRADES = 3

FULL_USDT = 6500.0
FULL_LEVERAGE = 50
FULL_MAX_TRADES = 7

CHECK_INTERVAL = 30

async def main():
    usdt_amount = SAFE_USDT if USE_SAFE_MODE else FULL_USDT
    leverage = SAFE_LEVERAGE if USE_SAFE_MODE else FULL_LEVERAGE
    max_trades = SAFE_MAX_TRADES if USE_SAFE_MODE else FULL_MAX_TRADES

    print(f"Bot started – {'SAFE MODE (Week 1)' if USE_SAFE_MODE else 'FULL MODE'}")
    print(f"Position: {usdt_amount * leverage} USDT | Max {max_trades} trades/day")

    # === READ API ID, HASH, BINGX API KEY FROM FILE ===
    creds = read_credentials('credentials.txt')
    api_id = int(creds['api_id'])
    api_hash = creds['api_hash']
    bingx_api_key = creds['bingx_api_key']

    # === PROMPT FOR PHONE + SECRET KEY ===
    phone = input("Enter Phone Number (with +): ").strip()
    secret_key = input("Enter BingX Secret Key: ").strip()

    if not phone or not secret_key:
        print("Phone and Secret Key are required!")
        return

    # === CREATE BINGX CLIENT ===
    client_bingx = {
        'api_key': bingx_api_key,
        'secret_key': secret_key,
        'base_url': 'https://open-api.bingx.com'
    }

    # === INIT & START TELEGRAM (interactive code) ===
    init_telegram(api_id, api_hash)
    try:
        print("Connecting to Telegram...")
        await telegram_client.start(phone=lambda: phone)  # Prompts for code
        print("Telegram connected!")
    except Exception as e:
        print(f"Telegram login failed: {e}")
        return

    daily_trades = 0
    last_reset = datetime.now().date()

    while True:
        try:
            if datetime.now().date() != last_reset:
                daily_trades = 0
                last_reset = datetime.now().date()
                print(f"Daily reset – {last_reset}")

            if daily_trades >= max_trades:
                await asyncio.sleep(3600)
                continue

            signals = await fetch_and_parse_telegram_signals(
                'credentials.txt', 'channel_details.txt', limit=10, n_signals=1
            )

            for signal in signals:
                if daily_trades >= max_trades:
                    break
                try:
                    await execute_trade(client_bingx, signal, usdt_amount, dry_run=False, custom_leverage=leverage)
                    daily_trades += 1
                except Exception as e:
                    print(f"[TRADE ERROR] {e}")

            await asyncio.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"[MAIN LOOP ERROR] {e}")
            await asyncio.sleep(60)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
