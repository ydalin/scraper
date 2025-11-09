# main.py
import asyncio
from datetime import datetime
from api import connect_bingx_futures
from telegram import fetch_and_parse_telegram_signals
from trade import execute_trade

# === SAFE MODE FOR WEEK 1 ===
SAFE_MODE_DAYS = 7
START_DATE = datetime.now().date()
USE_SAFE_MODE = (datetime.now().date() - START_DATE).days < SAFE_MODE_DAYS

# Settings
SAFE_USDT = 1000.0
SAFE_LEVERAGE = 20
SAFE_MAX_TRADES = 3

FULL_USDT = 6500.0
FULL_LEVERAGE = 50
FULL_MAX_TRADES = 7

CHECK_INTERVAL = 30  # seconds

async def main():
    usdt_amount = SAFE_USDT if USE_SAFE_MODE else FULL_USDT
    leverage = SAFE_LEVERAGE if USE_SAFE_MODE else FULL_LEVERAGE
    max_trades = SAFE_MAX_TRADES if USE_SAFE_MODE else FULL_MAX_TRADES

    print(f"Bot started – {'SAFE MODE (Week 1)' if USE_SAFE_MODE else 'FULL MODE'}")
    print(f"Position: {usdt_amount * leverage} USDT | Max {max_trades} trades/day")

    client, _, _ = await connect_bingx_futures('credentials.txt', is_demo=False)
    if not client:
        return

    daily_trades = 0
    last_reset = datetime.now().date()

    while True:
        if datetime.now().date() != last_reset:
            daily_trades = 0
            last_reset = datetime.now().date()
            print(f"Daily reset – {last_reset}")

        if daily_trades >= max_trades:
            print(f"Max trades reached: {max_trades}")
            await asyncio.sleep(3600)
            continue

        signals = await fetch_and_parse_telegram_signals(
            'credentials.txt', 'channel_details.txt', limit=10, n_signals=1
        )

        for signal in signals:
            if daily_trades >= max_trades:
                break
            await execute_trade(client, signal, usdt_amount, dry_run=False, custom_leverage=leverage)
            daily_trades += 1

        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    asyncio.run(main())