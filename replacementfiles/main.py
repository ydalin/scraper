# main.py – FINAL: Manual Leverage & Amount + 5/DAY + 4 TP + Daily Limits
import asyncio
from datetime import datetime
from api import bingx_api_request
from bot_telegram import parse_signal, init_telegram, read_credentials
import bot_telegram
from trade import execute_trade

# === DAILY SETTINGS ===
MAX_TRADES_PER_DAY = 5
DAILY_LOSS_LIMIT = -100.0
DAILY_PROFIT_TARGET = 200.0
CHECK_INTERVAL = 30

# === DAILY TRACKING ===
daily_trades = 0
last_reset = datetime.now().date()

async def reset_daily():
    global daily_trades, last_reset
    today = datetime.now().date()
    if today != last_reset:
        daily_trades = 0
        last_reset = today
        print(f"\nDaily reset: {today}")

async def get_total_pnl(client):
    resp = await bingx_api_request(
        'GET', '/openApi/swap/v2/account/balance',
        client['api_key'], client['secret_key'], client['base_url']
    )
    if resp.get('code') == 0:
        return float(resp['data'][0]['unrealizedProfit'])
    return 0.0

async def main():
    creds = read_credentials()
    init_telegram(creds['api_id'], creds['api_hash'])
    await bot_telegram.client.start()

    client_bingx = {
        'api_key': creds['bingx_api_key'],
        'secret_key': creds['bingx_secret_key'],
        'base_url': 'https://open-api.bingx.com'
    }

    # === MANUAL INPUT ===
    print("\n" + "="*60)
    usdt_amount = float(input("Enter amount per trade (USDT): "))
    leverage = int(input("Enter leverage (e.g. 20): "))
    print("="*60 + "\n")

    print(f"BOT STARTED – {usdt_amount} USDT | {leverage}x | MAX 5/DAY | LIVE\n")

    while True:
        await reset_daily()

        if daily_trades >= MAX_TRADES_PER_DAY:
            print(f"Max {MAX_TRADES_PER_DAY} trades reached. Sleeping 1h...")
            await asyncio.sleep(3600)
            continue

        current_pnl = await get_total_pnl(client_bingx)
        if current_pnl <= DAILY_LOSS_LIMIT:
            print(f"Daily loss limit: {current_pnl:.2f} USDT. Stopping.")
            break
        if current_pnl >= DAILY_PROFIT_TARGET:
            print(f"Profit target: {current_pnl:.2f} USDT. Closing all.")
            break

        # === FETCH SIGNAL ===
        signals = await bot_telegram.client.get_messages('me', limit=10)
        new_signal = None
        for msg in signals:
            if "PREMIUM SIGNAL" in msg.message:
                parsed = parse_signal(msg.message)
                if parsed:
                    new_signal = parsed
                    break

        if not new_signal:
            print("No new signal. Waiting...")
            await asyncio.sleep(CHECK_INTERVAL)
            continue

        print(f"\nEXECUTING TRADE {daily_trades+1}/{MAX_TRADES_PER_DAY}")
        await execute_trade(client_bingx, new_signal, usdt_amount, leverage, dry_run=False)
        daily_trades += 1

        await asyncio.sleep(CHECK_INTERVAL)

    print("\nBOT STOPPED")

if __name__ == '__main__':
    asyncio.run(main())
